from __future__ import annotations

import base64
import math
import mimetypes
import os
import re
import time
import urllib.request
from pathlib import Path


class VideoProviderError(RuntimeError):
    """Raised when an AI video provider cannot create a scene.

    ``fatal`` marks problems that will repeat for every scene (missing package, missing or
    rejected key, no credits), so the render should stop instead of falling back scene by scene.
    """

    def __init__(self, message: str, *, fatal: bool = False, retryable: bool = True):
        super().__init__(message)
        self.fatal = fatal
        self.retryable = retryable


class RunwayVideoProvider:
    """Generate realistic image-to-video clips with Runway Gen-4.5."""

    def __init__(self, *, model: str = "gen4.5", ratio: str = "720:1280"):
        self.model = model
        self.ratio = ratio

    def generate(
        self,
        *,
        prompt: str,
        image: Path | None,
        output: Path,
        duration: float,
        retries: int = 2,
    ) -> Path:
        try:
            from runwayml import RunwayML
        except ImportError as exc:
            raise VideoProviderError(
                "Runway motion requires the optional dependency. "
                "Install it with: python -m pip install runwayml",
                fatal=True,
            ) from exc

        if not os.getenv("RUNWAYML_API_SECRET"):
            raise VideoProviderError(
                "Runway motion requires RUNWAYML_API_SECRET in the environment. "
                "Keep the secret server-side; never put it in a prompt or source file.",
                fatal=True,
            )

        kwargs: dict[str, object] = {
            "model": self.model,
            "prompt_text": prompt,
            "ratio": self.ratio,
            "duration": clip_seconds(duration),
        }
        if image:
            kwargs["prompt_image"] = _data_uri(image)

        client = RunwayML()
        # With no scene image, image_to_video has nothing to animate and the API rejects the call.
        endpoint = client.image_to_video if image else client.text_to_video
        attempts = max(1, retries + 1)
        last_error: VideoProviderError | None = None
        for attempt in range(1, attempts + 1):
            try:
                task = endpoint.create(**kwargs).wait_for_task_output()
                return self._download(task, output)
            except VideoProviderError as exc:
                if exc.fatal or not exc.retryable:
                    raise
                last_error = exc
            except Exception as exc:
                last_error = classify_error(exc)
                if last_error.fatal or not last_error.retryable:
                    raise last_error from exc
            output.unlink(missing_ok=True)
            output.with_suffix(".tmp.mp4").unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(min(12, 2 ** (attempt - 1)))
        raise last_error or VideoProviderError("Runway motion generation failed for an unknown reason.")

    @staticmethod
    def _download(task: object, output: Path) -> Path:
        urls = getattr(task, "output", None)
        if urls is None and isinstance(task, dict):
            urls = task.get("output")
        if not isinstance(urls, (list, tuple)) or not urls or not isinstance(urls[0], str):
            raise VideoProviderError("Runway returned no downloadable video URL.")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.mp4")
        try:
            with urllib.request.urlopen(urls[0], timeout=180) as response:
                data = response.read()
            if len(data) < 10_000:
                raise VideoProviderError(f"downloaded video is unexpectedly small ({len(data)} bytes)")
            temporary.write_bytes(data)
            temporary.replace(output)
        except VideoProviderError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise VideoProviderError(f"Could not download Runway video: {exc}") from exc
        return output


_AUTH_WORDS = ("unauthorized", "invalid api key", "invalid api secret", "forbidden", "authentication")
_CREDIT_WORDS = ("insufficient credit", "not enough credit", "out of credit", "payment required")
_REJECT_WORDS = ("moderation", "content policy", "safety", "not allowed", "invalid", "unsupported")


def classify_error(exc: Exception) -> VideoProviderError:
    """Turn a Runway SDK error into a VideoProviderError, deciding what is worth retrying.

    The HTTP status is read from the exception when the SDK provides it. Guessing from digits in the message
    is unsafe: a request id such as "1403" would look like a 403 and abort the whole render.
    """
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if not isinstance(status, int):
        found = re.search(r"\b(?:error|status|code|http)[^0-9]{0,12}(4\d\d|5\d\d)\b", text)
        status = int(found.group(1)) if found else None
    fatal = status in (401, 402, 403) or any(w in text for w in _AUTH_WORDS + _CREDIT_WORDS)
    rejected = status in (400, 404, 413, 422) or any(w in text for w in _REJECT_WORDS)
    retryable = not fatal and not (rejected and status != 429)
    return VideoProviderError(f"Runway motion generation failed: {exc}", fatal=fatal, retryable=retryable)


def clip_seconds(duration: float) -> int:
    """Whole seconds to request from Runway: Gen-4.5 accepts 2-10, so don't pay for more than the scene needs."""
    return max(2, min(10, math.ceil(duration)))


def _data_uri(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"