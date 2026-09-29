from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import shutil
from pathlib import Path

from ..media import require_binary
from .planner import PlanError, plan_from_script, plan_from_topic, plan_script
from .render import (
    MotionRenderError,
    render_previews,
    render_video,
    scene_durations,
)
from .spec import DEFAULT_ACCENT, DEMO_SPEC, SpecError, normalize_spec

LOGGER = logging.getLogger("faceless_video_generator")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="faceless-motion",
        description="Create an animated motion-graphics video (typography, loop diagrams, charts) "
        "from a scene spec, a narration script, or a topic. No image generation service required.",
    )
    src = p.add_argument_group("source (pick one)")
    src.add_argument("--demo", action="store_true", help="Render the built-in 5-scene demo (habit loop).")
    src.add_argument("--spec", type=Path, help="Scene spec JSON file.")
    src.add_argument("--script", type=Path, help="Plain narration text; scenes are planned offline (or with --ai-plan).")
    src.add_argument("--topic", help="Let an online text model design the scenes for this topic.")
    p.add_argument("--output", "-o", type=Path, default=Path("output.mp4"))
    p.add_argument("--work-dir", type=Path, default=Path("work"))
    p.add_argument("--save-spec", type=Path, help="Write the final scene spec JSON here so you can edit and re-render it.")
    p.add_argument("--preview", type=Path, metavar="DIR", help="Write one PNG per scene to DIR and stop (fast look at the design).")
    p.add_argument("--dry-run", action="store_true", help="Print the scene plan and timings without rendering.")
    p.add_argument("--force", action="store_true", help="Replace an existing output file.")

    look = p.add_argument_group("look")
    look.add_argument("--width", type=int, default=1080)
    look.add_argument("--height", type=int, default=1920)
    look.add_argument("--fps", type=int, default=30)
    look.add_argument("--accent", default=None, help=f"Brand/highlight colour, default {DEFAULT_ACCENT}.")
    look.add_argument("--font", help="Path to a .ttf/.otf font (default: bundled Poppins).")
    look.add_argument("--no-caps", action="store_true", help="Keep text in its original case.")
    look.add_argument("--tag", default="KEY IDEA", help="Pill label used by --script planning.")
    look.add_argument("--preset", default="medium")
    look.add_argument("--crf", type=int, default=18)

    ai = p.add_argument_group("AI planning (--topic, or --script with --ai-plan)")
    ai.add_argument(
        "--ai-plan", action="store_true",
        help="With --script: a text model reads the script and picks a chart, diagram or typography scene for each part "
        "(your words are never changed; falls back to the offline planner if the model can't be used).",
    )
    ai.add_argument("--seconds", type=int, default=45, help="Target video length for --topic.")
    ai.add_argument("--text-provider", choices=["pollinations", "huggingface", "groq"], default="pollinations")
    ai.add_argument("--text-model", default="openai")

    audio = p.add_argument_group("audio (silent by default)")
    audio.add_argument("--narrate", action="store_true", help="Speak each scene's narration; scenes stretch to fit the voice.")
    audio.add_argument("--tts-provider", choices=["edge-tts", "huggingface"], default="edge-tts")
    audio.add_argument("--voice", default=None, help="Default: en-US-AndrewNeural (edge-tts) or am_michael (huggingface).")
    audio.add_argument("--voice-rate", default="+8%")
    audio.add_argument("--hf-tts-model", default="hexgrad/Kokoro-82M")
    audio.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    audio.add_argument("--music", type=Path, help="Background music file (looped, ducked under narration).")
    audio.add_argument("--auto-music", action="store_true", help="Use the generated ambient bed as background music.")
    audio.add_argument("--music-volume", type=float, default=0.08)
    p.add_argument("--verbose", action="store_true")
    return p


def _make_completer(args: argparse.Namespace):
    from ..script_writer import _complete_with_retry

    def completer(prompt: str) -> str:
        return _complete_with_retry(prompt, args.text_provider, args.text_model, args.hf_token, attempts=2)

    return completer


def _load_spec(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict:
    accent = args.accent or DEFAULT_ACCENT
    uppercase = not args.no_caps
    if args.demo:
        raw = copy.deepcopy(DEMO_SPEC)
        raw["style"] = {"accent": accent, "uppercase": uppercase}
        return normalize_spec(raw, uppercase=uppercase)
    if args.spec:
        try:
            raw = json.loads(args.spec.read_text(encoding="utf-8"))
        except FileNotFoundError:
            parser.error(f"spec file not found: {args.spec}")
        except json.JSONDecodeError as exc:
            parser.error(f"spec file is not valid JSON: {exc}")
        if args.accent and isinstance(raw, dict):
            raw.setdefault("style", {})["accent"] = args.accent
        return normalize_spec(raw, uppercase=uppercase)
    if args.script:
        try:
            text = args.script.read_text(encoding="utf-8")
        except FileNotFoundError:
            parser.error(f"script file not found: {args.script}")
        tag = args.tag.upper() if uppercase else args.tag
        completer = _make_completer(args) if args.ai_plan else None
        return plan_script(text, completer, tag=tag, accent=accent, uppercase=uppercase)
    if args.topic:
        LOGGER.info("Designing scenes for %r ...", args.topic)
        return plan_from_topic(args.topic, _make_completer(args), seconds=args.seconds, accent=accent)
    parser.error("choose a source: --demo, --spec FILE, --script FILE or --topic TEXT")


def _print_plan(spec: dict) -> None:
    durations = scene_durations(spec)
    print(f"{len(spec['scenes'])} scenes, about {sum(durations):.1f}s")
    for i, (scene, dur) in enumerate(zip(spec["scenes"], durations), 1):
        summary = scene.get("big") or scene.get("title") or " / ".join(scene.get("lines", [])) or scene.get("accent", "")
        if scene["type"] == "steps":
            summary = " > ".join(n["label"] for n in scene["nodes"])
        print(f"  {i:>2}. {scene['type']:<8} {scene['theme']:<6} {dur:>4.1f}s  {summary[:60]}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    if args.width < 64 or args.height < 64 or args.width % 2 or args.height % 2:
        parser.error("--width and --height must be even numbers of at least 64 pixels")
    if not 1 <= args.fps <= 120:
        parser.error("--fps must be between 1 and 120")
    if args.ai_plan and not args.script:
        parser.error("--ai-plan needs --script FILE")

    try:
        spec = _load_spec(args, parser)
    except (SpecError, PlanError, RuntimeError) as exc:
        parser.exit(1, f"error: {exc}\n")

    if args.save_spec:
        args.save_spec.parent.mkdir(parents=True, exist_ok=True)
        args.save_spec.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        LOGGER.info("Saved scene spec to %s", args.save_spec)
    if args.dry_run:
        _print_plan(spec)
        return

    try:
        if args.preview:
            for path in render_previews(spec, args.preview, width=args.width, height=args.height, font=args.font):
                print(path)
            return

        if args.output.exists() and not args.force:
            parser.exit(1, f"error: output already exists: {args.output}. Use --force to replace it.\n")
        ffmpeg = require_binary("ffmpeg")
        work_dir = args.work_dir.expanduser().resolve()
        music = args.music.expanduser() if args.music else None
        if music and not music.is_file():
            parser.exit(1, f"error: music file not found: {music}\n")
        if music is None and args.auto_music:
            from ..music import create_ambient_bed

            music = create_ambient_bed(ffmpeg, work_dir / "ambient-bed.wav", 30)

        synth = None
        if args.narrate:
            from .render import default_synthesizer

            synth = default_synthesizer(
                ffmpeg=ffmpeg, work_dir=work_dir, provider=args.tts_provider,
                voice=args.voice or ("am_michael" if args.tts_provider == "huggingface" else "en-US-AndrewNeural"),
                voice_rate=args.voice_rate, hf_model=args.hf_tts_model, hf_token=args.hf_token,
            )

        last = {"pct": -10}

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total)
            if pct >= last["pct"] + 10 or done == total:
                last["pct"] = pct
                LOGGER.info("Rendering frames: %d%%", pct)

        result = render_video(
            spec, args.output, ffmpeg=ffmpeg, width=args.width, height=args.height, fps=args.fps,
            preset=args.preset, crf=args.crf, font=args.font, work_dir=work_dir, synth=synth,
            music=music, music_volume=args.music_volume, on_progress=progress,
        )
        print(f"Created {result}")
    except (MotionRenderError, RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "cancelled\n")
