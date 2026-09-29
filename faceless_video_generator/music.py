from __future__ import annotations

import urllib.request
from pathlib import Path

from .media import run_command


def download_music(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "faceless-video-generator/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if len(data) < 10_000:
        raise RuntimeError("The music URL returned an unexpectedly small file.")
    temporary.write_bytes(data)
    temporary.replace(destination)
    return destination


def create_ambient_bed(ffmpeg: str, destination: Path, duration: float) -> Path:
    """Create a subtle royalty-free ambient bed as a deterministic fallback."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, duration)
    expression = (
        "0.35*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.08*t))"
        "+0.22*sin(2*PI*277.18*t)*(0.6+0.4*sin(2*PI*0.11*t))"
        "+0.18*sin(2*PI*329.63*t)*(0.6+0.4*sin(2*PI*0.13*t))"
    )
    run_command(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expression}:s=44100:d={duration:.3f}",
            "-af",
            f"afade=t=in:st=0:d=2,afade=t=out:st={max(0.0, duration - 2):.3f}:d=2",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    return destination