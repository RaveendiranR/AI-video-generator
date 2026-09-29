from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path

from .config import VideoConfig
from .pipeline import RenderError, VideoGenerator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faceless-video",
        description="Turn narration into a vertical faceless video with captions and optional AI images.",
    )
    parser.add_argument("--script", type=Path, default=Path("script.txt"))
    parser.add_argument("--output", type=Path, default=Path("output.mp4"))
    parser.add_argument("--work-dir", type=Path, default=Path("work"))
    parser.add_argument("--images-dir", type=Path, default=Path("images"))
    parser.add_argument("--ai-images-dir", type=Path, default=Path("ai_images"))
    parser.add_argument("--voice", default="en-US-AndrewNeural")
    parser.add_argument("--voice-rate", default="+8%", help="edge-tts speaking rate, e.g. +8%% or -5%%.")
    parser.add_argument("--min-scene-words", type=int, default=14, help="Merge short sentences into scenes of at least this many words (0 = one scene per sentence).")
    parser.add_argument("--no-motion", action="store_true", help="Disable zoom/pan on images.")
    parser.add_argument("--no-smart-prompts", action="store_true", help="Use narration text as image prompts.")
    parser.add_argument("--no-caps", action="store_true", help="Keep captions in normal case.")
    parser.add_argument("--tts-provider", choices=["edge-tts", "huggingface"], default="edge-tts")
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--hf-tts-model", default="hexgrad/Kokoro-82M")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--image-model",
        default="flux",
        help="Pollinations image model. flux is the default photorealistic free option.",
    )
    parser.add_argument(
        "--image-style",
        default=(
            "photorealistic cinematic documentary photography, physically accurate materials, "
            "natural skin texture, realistic lighting, subtle film grain, shallow depth of field, "
            "high detail, tasteful color grading"
        ),
    )
    parser.add_argument(
        "--video-provider",
        choices=["ken-burns", "runway"],
        default="ken-burns",
        help="ken-burns is local/free; runway creates real motion from each scene image.",
    )
    parser.add_argument("--video-model", default="gen4.5", help="Runway model for --video-provider runway.")
    parser.add_argument("--director-provider", choices=["auto", "anthropic", "pollinations", "huggingface", "none"], default="auto", help="AI story director backend. auto uses Claude when ANTHROPIC_API_KEY is present.")
    parser.add_argument("--director-model", default="claude-sonnet-4-6", help="Claude model used by the cinematic director.")
    parser.add_argument("--runway-retries", type=int, default=2, help="Extra retries for transient Runway failures.")
    parser.add_argument("--image-delay", type=float, default=16.0)
    parser.add_argument("--image-retries", type=int, default=3)
    parser.add_argument("--background", default="0x1a1a2e")
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--caption-font-size", type=int, default=0, help="0 = automatic.")
    parser.add_argument("--caption-margin", type=int, default=0, help="0 = automatic.")
    parser.add_argument("--music", type=Path, help="Local royalty-free music file.")
    parser.add_argument("--music-url", help="Download a royalty-free music file before rendering.")
    parser.add_argument("--music-volume", type=float, default=0.08)
    parser.add_argument("--no-music", action="store_true", help="Disable the generated ambient music fallback.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--no-ai-images", action="store_true", help="Use local images or a solid background only.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore the work manifest and rebuild every scene.")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and show the planned render without running FFmpeg.")
    parser.add_argument("--check", action="store_true", help="Check FFmpeg and FFprobe availability, then exit.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.check:
        for binary in ("ffmpeg", "ffprobe"):
            path = shutil.which(binary)
            print(f"{binary}: {path or 'missing'}")
        return

    config = VideoConfig(
        script=args.script,
        output=args.output,
        work_dir=args.work_dir,
        images_dir=args.images_dir,
        ai_images_dir=args.ai_images_dir,
        width=args.width,
        height=args.height,
        fps=args.fps,
        voice=args.voice,
        voice_rate=args.voice_rate,
        min_scene_words=args.min_scene_words,
        motion=not args.no_motion,
        smart_prompts=not args.no_smart_prompts,
        caption_uppercase=not args.no_caps,
        tts_provider=args.tts_provider,
        hf_token=args.hf_token,
        hf_tts_model=args.hf_tts_model,
        image_model=args.image_model,
        image_style=args.image_style,
        video_provider=args.video_provider,
        video_model=args.video_model,
        director_provider=args.director_provider,
        director_model=args.director_model,
        runway_retries=args.runway_retries,
        use_ai_images=not args.no_ai_images,
        image_delay=args.image_delay,
        image_retries=args.image_retries,
        background=args.background,
        preset=args.preset,
        crf=args.crf,
        caption_font_size=args.caption_font_size,
        caption_margin=args.caption_margin,
        music=args.music,
        music_url=args.music_url,
        music_volume=args.music_volume,
        auto_music=not args.no_music,
        seed=args.seed,
        force=args.force,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )
    try:
        output = VideoGenerator(config).render()
        print(f"Created {output}")
    except (RenderError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "cancelled\n")