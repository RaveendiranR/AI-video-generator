from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .config import VideoConfig
from .pipeline import VideoGenerator
from .script_writer import write_script
from .trends import fetch_google_trends
from .youtube_upload import upload_video


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create a complete faceless video from a topic, then optionally upload it."
    )
    parser.add_argument("--topic")
    parser.add_argument("--from-trends", action="store_true")
    parser.add_argument("--region", default="US")
    parser.add_argument("--script", type=Path, default=Path("script.txt"))
    parser.add_argument("--output", type=Path, default=Path("output.mp4"))
    parser.add_argument("--text-provider", choices=["pollinations", "huggingface"], default="pollinations")
    parser.add_argument("--text-model", default="openai")
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--tts-provider", choices=["edge-tts", "huggingface"], default="edge-tts")
    parser.add_argument(
        "--seconds",
        type=int,
        default=600,
        help="Target narration duration in seconds (default: 600; use 60 for a short video).",
    )
    parser.add_argument("--voice", default=None, help="Default: en-US-AndrewNeural (edge-tts) or am_michael (huggingface).")
    parser.add_argument("--min-scene-words", type=int, default=14)
    parser.add_argument("--voice-rate", default="+8%", help="edge-tts speaking rate.")
    parser.add_argument("--hf-tts-model", default="hexgrad/Kokoro-82M")
    parser.add_argument("--no-ai-images", action="store_true")
    parser.add_argument("--no-motion", action="store_true")
    parser.add_argument("--no-smart-prompts", action="store_true")
    parser.add_argument("--no-caps", action="store_true")
    parser.add_argument("--image-model", default="flux")
    parser.add_argument(
        "--image-style",
        default=(
            "photorealistic cinematic documentary photography, physically accurate materials, "
            "natural skin texture, realistic lighting, subtle film grain, shallow depth of field, "
            "high detail, tasteful color grading"
        ),
    )
    parser.add_argument("--video-provider", choices=["ken-burns", "runway"], default="ken-burns")
    parser.add_argument("--video-model", default="gen4.5")
    parser.add_argument("--director-provider", choices=["auto", "anthropic", "pollinations", "huggingface", "none"], default="auto")
    parser.add_argument("--director-model", default="claude-sonnet-4-6")
    parser.add_argument("--runway-retries", type=int, default=2)
    parser.add_argument("--caption-font-size", type=int, default=0)
    parser.add_argument("--caption-margin", type=int, default=0)
    parser.add_argument("--music", type=Path)
    parser.add_argument("--music-url")
    parser.add_argument("--music-volume", type=float, default=0.08)
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--publish-at")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.topic and not args.from_trends:
        parser.error("provide --topic or use --from-trends")
    if args.seconds < 10:
        parser.error("--seconds must be at least 10")
    if args.from_trends:
        trends = fetch_google_trends(args.region, limit=1)
        if not trends:
            parser.error("Google Trends returned no topics")
        args.topic = trends[0].title

    try:
        text = write_script(
            args.topic,
            provider=args.text_provider,
            model=args.text_model,
            seconds=args.seconds,
            hf_token=args.hf_token,
        )
        args.script.write_text(text + "\n", encoding="utf-8")
        config = VideoConfig(
            script=args.script,
            output=args.output,
            voice=args.voice or ("am_michael" if args.tts_provider == "huggingface" else "en-US-AndrewNeural"),
            min_scene_words=args.min_scene_words,
            voice_rate=args.voice_rate,
            tts_provider=args.tts_provider,
            hf_tts_model=args.hf_tts_model,
            hf_token=args.hf_token,
            image_model=args.image_model,
            image_style=args.image_style,
            video_provider=args.video_provider,
            video_model=args.video_model,
            director_provider=args.director_provider,
            director_model=args.director_model,
            runway_retries=args.runway_retries,
            use_ai_images=not args.no_ai_images,
            motion=not args.no_motion,
            smart_prompts=not args.no_smart_prompts,
            caption_uppercase=not args.no_caps,
            caption_font_size=args.caption_font_size,
            caption_margin=args.caption_margin,
            music=args.music,
            music_url=args.music_url,
            music_volume=args.music_volume,
            auto_music=not args.no_music,
            force=True,
        )
        output = VideoGenerator(config).render()
        print(f"Created {output}")
        if args.upload:
            title = args.title or args.topic
            url = upload_video(
                output,
                title=title,
                description=args.description,
                tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()],
                client_secret=args.client_secret,
                privacy=args.privacy,
                publish_at=args.publish_at,
            )
            print(f"Uploaded: {url}")
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()