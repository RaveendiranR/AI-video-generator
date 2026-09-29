from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "faceless-video-generator/1.13.1"
ANTHROPIC_VERSION = "2023-06-01"


class OnlineAIError(RuntimeError):
    """Raised when an online model cannot complete a request."""


def generate_text(
    prompt: str,
    *,
    provider: str = "pollinations",
    model: str = "openai",
    hf_token: str | None = None,
    timeout: int = 120,
) -> str:
    """Generate text with a no-key Pollinations endpoint or Hugging Face."""
    if provider == "pollinations":
        url = (
            "https://text.pollinations.ai/"
            + urllib.parse.quote(prompt, safe="")
            + "?model="
            + urllib.parse.quote(model, safe="")
        )
        headers = {"User-Agent": USER_AGENT}
        key = os.getenv("POLLINATIONS_API_KEY")
        if key:  # the keyless endpoint is being retired; use the key when one is configured
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(url, headers=headers)
        return _read_text(request, timeout)

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise OnlineAIError("ANTHROPIC_API_KEY is required for the Claude director.")
        payload = {
            "model": model or "claude-sonnet-4-6",
            "max_tokens": 16000,  # a 60-scene director plan is ~6k tokens; a low cap truncates the JSON
            "messages": [{"role": "user", "content": prompt}],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
                "user-agent": USER_AGENT,
            },
            method="POST",
        )
        response = _read_json(request, max(timeout, 300), service="Claude")
        if isinstance(response, dict):
            content = response.get("content")
            if isinstance(content, list):
                parts = [str(item.get("text", "")).strip() for item in content if isinstance(item, dict) and item.get("type") == "text"]
                text = "\n".join(part for part in parts if part)
            else:
                text = ""
        else:
            text = ""
        if not text:
            raise OnlineAIError("Claude returned no text content.")
        return text.strip()

    if provider == "huggingface":
        if not hf_token:
            raise OnlineAIError("HF_TOKEN is required for the Hugging Face provider.")
        url = f"https://api-inference.huggingface.co/models/{model}"
        request = urllib.request.Request(
            url,
            data=json.dumps({"inputs": prompt, "parameters": {"max_new_tokens": 900}}).encode(),
            headers={
                "Authorization": f"Bearer {hf_token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        payload = _read_json(request, timeout)
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            text = payload[0].get("generated_text", "")
        elif isinstance(payload, dict):
            text = payload.get("generated_text", "")
        else:
            text = ""
        if not text:
            raise OnlineAIError("The Hugging Face model returned no generated text.")
        return str(text).strip()

    raise OnlineAIError(f"Unsupported text provider: {provider}")


def synthesize_huggingface(
    text: str,
    *,
    model: str = "hexgrad/Kokoro-82M",
    voice: str = "af_heart",
    hf_token: str | None = None,
    timeout: int = 180,
) -> bytes:
    """Request audio from an open text-to-speech model hosted by Hugging Face."""
    if not hf_token:
        raise OnlineAIError("HF_TOKEN is required for Hugging Face text-to-speech.")
    url = f"https://api-inference.huggingface.co/models/{model}"
    request = urllib.request.Request(
        url,
        data=json.dumps({"inputs": text, "parameters": {"voice": voice}}).encode(),
        headers={
            "Authorization": f"Bearer {hf_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise OnlineAIError(f"Hugging Face TTS failed ({exc.code}): {details[:500]}") from exc
    except OSError as exc:
        raise OnlineAIError(f"Hugging Face TTS request failed: {exc}") from exc
    if not data or ("audio" not in content_type and not data.startswith(b"RIFF")):
        raise OnlineAIError("Hugging Face TTS returned a non-audio response.")
    return data


def _read_text(request: urllib.request.Request, timeout: int) -> str:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise OnlineAIError(f"Online text model failed ({exc.code}): {details[:500]}") from exc
    except OSError as exc:
        raise OnlineAIError(f"Online text model request failed: {exc}") from exc
    if not text:
        raise OnlineAIError("The online text model returned an empty response.")
    return text


def _read_json(request: urllib.request.Request, timeout: int, service: str = "Hugging Face") -> object:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        if exc.code in (429, 503):
            time.sleep(2)
        raise OnlineAIError(f"{service} request failed ({exc.code}): {details[:500]}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise OnlineAIError(f"Could not read the {service} response: {exc}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        raise OnlineAIError(str(error.get("message", error)) if isinstance(error, dict) else str(error))
    return payload