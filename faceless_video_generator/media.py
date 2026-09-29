from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class CommandError(RuntimeError):
    """Raised when an external media command fails."""


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        if name == "ffmpeg":
            try:
                import imageio_ffmpeg

                return imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError, RuntimeError):
                pass
        raise RuntimeError(
            f"'{name}' was not found on PATH. Install FFmpeg or install the bundled "
            "imageio-ffmpeg package."
        )
    return path


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> None:
    printable = " ".join(_quote_for_log(part) for part in command)
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise CommandError(f"Could not start command: {printable}\n{exc}") from exc

    if completed.returncode:
        details = (completed.stderr or completed.stdout).strip()
        if len(details) > 4000:
            details = details[-4000:]
        raise CommandError(
            f"Command failed with exit code {completed.returncode}: {printable}\n{details}"
        )


def probe_duration(ffmpeg: str, path: Path) -> float | None:
    """Length of a media file in seconds, read from ``ffmpeg -i`` (works without ffprobe)."""
    try:
        completed = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                                   capture_output=True, text=True, check=False)
    except OSError:
        return None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", completed.stderr or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _quote_for_log(value: str) -> str:
    return value if value.replace("_", "").replace("-", "").isalnum() else repr(value)


def concat_escape(path: str) -> str:
    """Escape a path for an FFmpeg concat-demuxer file."""
    return path.replace("\\", "\\\\").replace("'", "'\\''")