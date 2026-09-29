"""Render a normalised scene spec to MP4: procedural frames piped straight into FFmpeg."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from ..media import CommandError, run_command
from .draw import resolve_font_path
from .scenes import RENDERERS, Ctx
from .spec import THEME_NAMES, Theme, make_theme

LOGGER = logging.getLogger("faceless_video_generator")

Synthesizer = Callable[[str, Path], None]
NARRATION_TAIL = 0.4  # seconds of breathing room after each spoken scene


class MotionRenderError(RuntimeError):
    """Raised when a motion-graphics render fails."""


def build_context(width: int, height: int, font: str | None = None) -> Ctx:
    try:
        bold = resolve_font_path("bold", font)
        medium = resolve_font_path("medium", font)
    except FileNotFoundError as exc:
        raise MotionRenderError(str(exc)) from exc
    return Ctx(width, height, bold, medium)


def build_themes(spec: dict[str, Any]) -> dict[str, Theme]:
    accent = spec["style"]["accent"]
    return {name: make_theme(name, accent) for name in THEME_NAMES}


def render_frame(scene: dict[str, Any], t: float, ctx: Ctx, themes: dict[str, Theme]) -> Image.Image:
    theme = themes[scene["theme"]]
    canvas = Image.new("RGB", (ctx.w, ctx.h), theme.bg)
    RENDERERS[scene["type"]](canvas, scene, t, ctx, theme)
    return canvas


def frame_counts(durations: Sequence[float], fps: int) -> list[int]:
    return [max(1, round(d * fps)) for d in durations]


def scene_durations(spec: dict[str, Any], narration_lengths: Sequence[float | None] | None = None) -> list[float]:
    """Scene lengths in seconds; narrated scenes are stretched to fit their audio."""
    lengths = narration_lengths or [None] * len(spec["scenes"])
    out = []
    for scene, spoken in zip(spec["scenes"], lengths):
        out.append(max(scene["duration"], spoken + NARRATION_TAIL) if spoken else scene["duration"])
    return out


def render_previews(spec: dict[str, Any], directory: Path, *, width: int, height: int, font: str | None = None) -> list[Path]:
    """Write one PNG per scene (near its end, when everything has animated in)."""
    ctx = build_context(width, height, font)
    themes = build_themes(spec)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, scene in enumerate(spec["scenes"]):
        path = directory / f"scene-{i + 1:02d}-{scene['type']}.png"
        render_frame(scene, scene["duration"] * 0.9, ctx, themes).save(path)
        paths.append(path)
    return paths


def render_silent_video(
    spec: dict[str, Any],
    output: Path,
    *,
    ffmpeg: str,
    width: int,
    height: int,
    fps: int,
    durations: Sequence[float],
    preset: str = "medium",
    crf: int = 18,
    font: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    ctx = build_context(width, height, font)
    themes = build_themes(spec)
    counts = frame_counts(durations, fps)
    total = sum(counts)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", "-an", str(output),
    ]
    done = 0
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        except OSError as exc:
            raise MotionRenderError(f"Could not start FFmpeg: {exc}") from exc
        assert process.stdin is not None
        try:
            for scene, count in zip(spec["scenes"], counts):
                for frame in range(count):
                    process.stdin.write(render_frame(scene, frame / fps, ctx, themes).tobytes())
                    done += 1
                    if on_progress and (done % fps == 0 or done == total):
                        on_progress(done, total)
        except BrokenPipeError:
            pass
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            code = process.wait()
        if code:
            errors.seek(0)
            details = errors.read().decode("utf-8", "replace").strip()[-3000:]
            raise MotionRenderError(f"FFmpeg failed while encoding frames (exit {code}).\n{details}")


# --------------------------------------------------------------------------- audio
def synthesize_scenes(spec: dict[str, Any], work_dir: Path, synth: Synthesizer) -> list[Path | None]:
    """Create (or reuse) a narration WAV for each scene that has narration text."""
    from ..pipeline import wav_duration  # local import: pipeline is heavy

    work_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path | None] = []
    for i, scene in enumerate(spec["scenes"]):
        text = scene["narration"]
        if not text:
            paths.append(None)
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        path = work_dir / f"motion-voice-{digest}.wav"
        if not path.exists():
            LOGGER.info("[%d/%d] narrating: %s", i + 1, len(spec["scenes"]), text[:80])
            synth(text, path)
        wav_duration(path)  # fail early on a corrupt file
        paths.append(path)
    return paths


def narration_lengths(paths: Sequence[Path | None]) -> list[float | None]:
    from ..pipeline import wav_duration

    return [wav_duration(p) if p else None for p in paths]


def build_audio_track(
    ffmpeg: str,
    wavs: Sequence[Path | None],
    durations: Sequence[float],
    output: Path,
    *,
    music: Path | None = None,
    music_volume: float = 0.08,
) -> Path:
    """Concatenate per-scene narration (padded to each scene's length) and mix in music."""
    total = sum(durations)
    command: list[str] = [ffmpeg, "-y", "-loglevel", "error"]
    chains: list[str] = []
    has_voice = any(wavs)
    if has_voice:
        for i, (wav, dur) in enumerate(zip(wavs, durations)):
            if wav:
                command += ["-i", str(wav)]
            else:
                command += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
            chains.append(
                f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,"
                f"apad=whole_dur={dur:.3f},atrim=0:{dur:.3f},asetpts=N/SR/TB[a{i}]"
            )
        joined = "".join(f"[a{i}]" for i in range(len(wavs)))
        chains.append(f"{joined}concat=n={len(wavs)}:v=0:a=1[voice]")
    if music:
        m = len(wavs) if has_voice else 0
        command += ["-stream_loop", "-1", "-i", str(music)]
        chains.append(
            f"[{m}:a]aresample=44100,aformat=channel_layouts=mono,volume={music_volume:.3f},"
            f"atrim=0:{total:.3f},afade=t=in:d=1,afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5[mus]"
        )
        if has_voice:
            chains.append("[voice]asplit=2[v1][v2]")
            chains.append("[mus][v1]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=250[duck]")
            chains.append("[v2][duck]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed]")
            final = "[mixed]"
        else:
            final = "[mus]"
    elif has_voice:
        final = "[voice]"
    else:
        raise MotionRenderError("build_audio_track needs narration or music.")
    chains.append(f"{final}loudnorm=I=-14:TP=-1.5:LRA=11[out]")
    command += ["-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(output)]
    run_command(command)
    return output


def mux_audio(ffmpeg: str, video: Path, audio: Path, output: Path) -> None:
    run_command(
        [
            ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(output),
        ]
    )


def render_video(
    spec: dict[str, Any],
    output: Path,
    *,
    ffmpeg: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    preset: str = "medium",
    crf: int = 18,
    font: str | None = None,
    work_dir: Path | None = None,
    synth: Synthesizer | None = None,
    music: Path | None = None,
    music_volume: float = 0.08,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Render ``spec`` to ``output``. Silent unless ``synth`` (narration) or ``music`` is given."""
    if width % 2 or height % 2:
        raise MotionRenderError("Width and height must be even numbers for H.264 output.")
    work_dir = work_dir or output.parent / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    wavs: list[Path | None] = [None] * len(spec["scenes"])
    if synth is not None:
        try:
            wavs = synthesize_scenes(spec, work_dir, synth)
        except (CommandError, RuntimeError, OSError) as exc:
            raise MotionRenderError(f"Narration failed: {exc}") from exc
    durations = scene_durations(spec, narration_lengths(wavs) if synth is not None else None)
    want_audio = any(wavs) or music is not None

    silent = work_dir / "motion-silent.mp4"
    target = silent if want_audio else output.with_suffix(".tmp.mp4")
    render_silent_video(
        spec, target, ffmpeg=ffmpeg, width=width, height=height, fps=fps,
        durations=durations, preset=preset, crf=crf, font=font, on_progress=on_progress,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if want_audio:
        # Actual playback length follows the frame count, so pad audio to that.
        video_durations = [c / fps for c in frame_counts(durations, fps)]
        track = build_audio_track(
            ffmpeg, wavs, video_durations, work_dir / "motion-audio.wav",
            music=music, music_volume=music_volume,
        )
        temporary = output.with_suffix(".tmp.mp4")
        mux_audio(ffmpeg, silent, track, temporary)
        temporary.replace(output)
    else:
        target.replace(output)
    return output


def default_synthesizer(
    *, ffmpeg: str, work_dir: Path, provider: str, voice: str, voice_rate: str, hf_model: str, hf_token: str | None
) -> Synthesizer:
    """Reuse the photo pipeline's TTS (edge-tts or Hugging Face Kokoro) for scene narration."""
    from ..config import VideoConfig
    from ..pipeline import VideoGenerator

    generator = VideoGenerator(
        VideoConfig(
            script=work_dir / "script.txt", work_dir=work_dir, ai_images_dir=work_dir,
            tts_provider=provider, voice=voice, voice_rate=voice_rate,
            hf_tts_model=hf_model, hf_token=hf_token,
        )
    )
    generator.ffmpeg = ffmpeg
    return generator._synthesize
