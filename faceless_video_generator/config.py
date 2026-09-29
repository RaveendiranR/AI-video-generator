from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class VideoConfig:
    """All knobs for a render, kept in one serializable object."""

    script: Path = Path("script.txt")
    output: Path = Path("output.mp4")
    work_dir: Path = Path("work")
    images_dir: Path = Path("images")
    ai_images_dir: Path = Path("ai_images")
    width: int = 1080
    height: int = 1920
    fps: int = 30
    voice: str = "en-US-AndrewNeural"
    voice_rate: str = "+8%"
    tts_provider: str = "edge-tts"
    hf_tts_model: str = "hexgrad/Kokoro-82M"
    hf_token: str | None = None
    image_model: str = "flux"
    image_style: str = (
        "photorealistic cinematic documentary photography, physically accurate materials, "
        "natural skin texture, realistic lighting, subtle film grain, shallow depth of field, "
        "high detail, tasteful color grading"
    )
    use_ai_images: bool = True
    video_provider: str = "ken-burns"
    video_model: str = "gen4.5"
    director_provider: str = "auto"
    director_model: str = "claude-sonnet-4-6"
    runway_retries: int = 2
    smart_prompts: bool = True
    motion: bool = True
    motion_strength: float = 0.14
    caption_uppercase: bool = True
    image_delay: float = 16.0
    image_retries: int = 3
    scene_padding: float = 0.25
    min_scene_words: int = 14
    background: str = "0x1a1a2e"
    preset: str = "medium"
    crf: int = 18
    caption_font_size: int = 0
    caption_margin: int = 0
    music: Path | None = None
    music_url: str | None = None
    music_volume: float = 0.08
    auto_music: bool = True
    seed: int = 1
    force: bool = False
    resume: bool = True
    dry_run: bool = False
    extra_env: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.width < 64 or self.height < 64:
            raise ValueError("Video dimensions must each be at least 64 pixels.")
        if self.fps < 1 or self.fps > 120:
            raise ValueError("FPS must be between 1 and 120.")
        if self.tts_provider not in {"edge-tts", "huggingface"}:
            raise ValueError("TTS provider must be edge-tts or huggingface.")
        if self.video_provider not in {"ken-burns", "runway"}:
            raise ValueError("Video provider must be ken-burns or runway.")
        if self.director_provider not in {"auto", "anthropic", "pollinations", "huggingface", "none"}:
            raise ValueError("Director provider must be auto, anthropic, pollinations, huggingface, or none.")
        if self.runway_retries < 0 or self.runway_retries > 5:
            raise ValueError("Runway retries must be between 0 and 5.")
        if self.image_delay < 0:
            raise ValueError("Image delay cannot be negative.")
        if self.image_retries < 1:
            raise ValueError("Image retries must be at least 1.")
        if not 0 <= self.crf <= 51:
            raise ValueError("CRF must be between 0 and 51.")
        if self.min_scene_words < 0:
            raise ValueError("Minimum scene words cannot be negative.")
        if self.scene_padding < 0:
            raise ValueError("Scene padding cannot be negative.")
        if self.caption_font_size < 0 or self.caption_margin < 0:
            raise ValueError("Caption font size and margin cannot be negative.")
        if not 0 <= self.motion_strength <= 0.5:
            raise ValueError("Motion strength must be between 0 and 0.5.")
        if not 0 < self.music_volume <= 1:
            raise ValueError("Music volume must be greater than 0 and at most 1.")

    @property
    def base_dir(self) -> Path:
        return self.script.expanduser().resolve().parent

    def resolve(self) -> "VideoConfig":
        """Resolve all paths relative to the script, not the caller's cwd."""
        base = self.base_dir

        def resolve_path(path: Path) -> Path:
            return path.expanduser() if path.is_absolute() else base / path

        resolved = {
            "script": resolve_path(self.script),
            "output": resolve_path(self.output),
            "work_dir": resolve_path(self.work_dir),
            "images_dir": resolve_path(self.images_dir),
            "ai_images_dir": resolve_path(self.ai_images_dir),
        }
        if self.music is not None:
            resolved["music"] = resolve_path(self.music)
        return VideoConfig(
            **{field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__ if field_name not in resolved},
            **resolved,
        )

    def to_manifest_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "voice": self.voice,
            "voice_rate": self.voice_rate,
            "smart_prompts": self.smart_prompts,
            "motion": self.motion,
            "motion_strength": self.motion_strength,
            "caption_uppercase": self.caption_uppercase,
            "tts_provider": self.tts_provider,
            "hf_tts_model": self.hf_tts_model,
            "image_style": self.image_style,
            "image_model": self.image_model,
            "use_ai_images": self.use_ai_images,
            "video_provider": self.video_provider,
            "video_model": self.video_model,
            "director_provider": self.director_provider,
            "director_model": self.director_model,
            "runway_retries": self.runway_retries,
            "scene_padding": self.scene_padding,
            "min_scene_words": self.min_scene_words,
            "background": self.background,
            "preset": self.preset,
            "crf": self.crf,
            "caption_font_size": self.caption_font_size,
            "caption_margin": self.caption_margin,
            "music": str(self.music) if self.music else None,
            "music_url": self.music_url,
            "music_volume": self.music_volume,
            "auto_music": self.auto_music,
        }