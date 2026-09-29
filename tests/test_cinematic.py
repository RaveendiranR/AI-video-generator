"""Creator Pro (Runway) mode: director, prompt limits, clip validation, fallback, looping, versions."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import faceless_video_generator as package
from faceless_video_generator import webui
from faceless_video_generator.config import VideoConfig
from faceless_video_generator.director import MAX_PROMPT_CHARS, SHOT_LIBRARY, build_prompt, plan_shot
from faceless_video_generator.media import probe_duration
from faceless_video_generator.pipeline import RenderError, VideoGenerator
from faceless_video_generator.video_generation import RunwayVideoProvider, VideoProviderError, clip_seconds

ROOT = Path(__file__).resolve().parents[1]
BIBLE = {
    "recurring_subjects": ["A courier in a red jacket", "Her grey scooter"],
    "recurring_locations": ["Old night market", "Rain-slick alley"],
    "continuity_rules": ["Same red jacket in every shot", "Rainy night, neon reflections", "No daylight"] * 3,
}


def _make_clip(ffmpeg: str, path: Path, seconds: int) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc2=size=160x284:rate=12:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def _generator(tmp: str, **overrides) -> VideoGenerator:
    script = Path(tmp) / "script.txt"
    script.write_text("Hello there.", encoding="utf-8")
    config = VideoConfig(script=script, video_provider="runway", smart_prompts=False,
                         preset="ultrafast", crf=32, width=160, height=284, **overrides).resolve()
    config.work_dir.mkdir(parents=True, exist_ok=True)
    return VideoGenerator(config)


def _image(tmp: str) -> Path:
    path = Path(tmp) / "img.png"
    path.write_bytes(b"x")
    return path


class VersionTest(unittest.TestCase):
    def test_versions_agree(self):
        pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        frontend = json.loads((ROOT / "frontend" / "package.json").read_text())["version"]
        self.assertEqual(package.__version__, pyproject)
        self.assertEqual(frontend, pyproject)

    def test_requirements_are_clean(self):
        lines = [l for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), len({l.split(">")[0] for l in lines}))
        self.assertFalse(any(l.startswith("#") for l in lines))


class DirectorTest(unittest.TestCase):
    def test_never_repeats_the_previous_shot(self):
        previous = None
        for index in range(40):
            plan = plan_shot(index, "The door opens and she walks in." if index % 2 else "A quiet room.", previous)
            if previous:
                self.assertNotEqual(plan.shot, previous.shot)
            previous = plan

    def test_story_beats_pick_matching_shots(self):
        self.assertEqual(plan_shot(1, "She walks down the street.").shot, "medium action")
        self.assertEqual(plan_shot(1, "A shocking discovery.").shot, "low-angle reveal")

    def test_prompt_fits_the_limit_even_with_a_huge_bible(self):
        huge = {k: v * 20 for k, v in BIBLE.items()}
        for plan in SHOT_LIBRARY:
            prompt = build_prompt(visual="A courier runs through a market. " * 30, sentence="He runs.",
                                  bible=huge, plan=plan, first=True)
            self.assertLessEqual(len(prompt), MAX_PROMPT_CHARS)
            self.assertIn(plan.lens, prompt)            # shot direction is never the part that gets trimmed
            self.assertIn("No text, logos", prompt)     # neither is the realism guard

    def test_prompt_is_readable_and_carries_continuity(self):
        prompt = build_prompt(visual="A courier runs.", sentence="He runs.", bible=BIBLE, plan=SHOT_LIBRARY[1])
        self.assertIn("red jacket", prompt)
        self.assertNotIn("['", prompt)                  # no Python list reprs leaking into the prompt
        self.assertLessEqual(len(prompt), MAX_PROMPT_CHARS)

    def test_hook_only_on_opening_shot(self):
        first = build_prompt(visual="v", sentence="s", bible={}, plan=SHOT_LIBRARY[0], first=True)
        later = build_prompt(visual="v", sentence="s", bible={}, plan=SHOT_LIBRARY[0])
        self.assertIn("Opening shot", first)
        self.assertNotIn("Opening shot", later)



from faceless_video_generator.script_writer import plan_cinematic_storyboard
class RunwayTest(unittest.TestCase):
    def test_setup_errors_are_fatal(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.dict("sys.modules", {"runwayml": mock.MagicMock()}):
            with self.assertRaises(VideoProviderError) as ctx:
                RunwayVideoProvider().generate(prompt="p", image=None, output=Path("x.mp4"), duration=3)
        self.assertTrue(ctx.exception.fatal)

    def test_requested_seconds_stay_in_range_and_do_not_overpay(self):
        self.assertEqual(clip_seconds(0.4), 2)
        self.assertEqual(clip_seconds(3.2), 4)
        self.assertEqual(clip_seconds(99), 10)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class ClipHandlingTest(unittest.TestCase):
    def test_a_good_clip_passes_validation(self):
        """Regression: v1.12 crashed here (run_command has no capture_output), so every render failed."""
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            clip = Path(tmp) / "good.mp4"
            _make_clip(gen.ffmpeg, clip, 5)
            self.assertAlmostEqual(gen._validate_motion_clip(clip), 5.0, delta=0.3)

    def test_broken_clips_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            tiny = Path(tmp) / "tiny.mp4"
            tiny.write_bytes(b"x" * 100)
            garbage = Path(tmp) / "garbage.mp4"
            garbage.write_bytes(b"not a video" * 5000)
            short = Path(tmp) / "short.mp4"
            subprocess.run([gen.ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=1280x720:rate=30:duration=0.5", "-pix_fmt", "yuv420p", str(short)], check=True)
            for bad in (tiny, garbage, short, Path(tmp) / "missing.mp4"):
                with self.subTest(bad.name), self.assertRaises(RenderError):
                    gen._validate_motion_clip(bad)

    def test_successful_generation_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)

            def fake(self, *, prompt, image, output, duration, retries=2):
                _make_clip(gen.ffmpeg, output, 3)
                # enlarge past the size floor
                with output.open("ab") as handle:
                    handle.write(b"\0" * 30_000)
                return output

            with mock.patch.object(RunwayVideoProvider, "generate", fake):
                result = gen._select_motion_video(index=0, sentence="Hi.", image=_image(tmp), duration=3)
            self.assertIsNotNone(result)
            self.assertTrue(result.exists())

    def test_short_clip_becomes_a_boomerang_and_long_clip_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            clip = Path(tmp) / "clip.mp4"
            _make_clip(gen.ffmpeg, clip, 2)
            self.assertAlmostEqual(probe_duration(gen.ffmpeg, clip), 2.0, delta=0.2)
            self.assertEqual(gen._loopable(clip, 1.5), clip)
            looped = gen._loopable(clip, 5.0)
            self.assertNotEqual(looped, clip)
            self.assertAlmostEqual(probe_duration(gen.ffmpeg, looped), 4.0, delta=0.3)
            self.assertEqual(gen._loopable(clip, 5.0), looped)



class ClaudeDirectorTest(unittest.TestCase):
    def test_director_json_is_compact_and_preserves_scene_count(self):
        sentences = ["A courier enters the station.", "He notices a red envelope."]
        raw = json.dumps({
            "story_summary": "A courier notices a clue.",
            "visual_bible": {"palette": "cool blue", "subjects": ["courier in red jacket"]},
            "scenes": [
                {"visual": "Courier enters an old station at dawn", "beat": "He moves toward the platforms", "shot": "tracking", "transition": "cut", "energy": "curious"},
                {"visual": "Red envelope resting on a bench", "beat": "His attention locks onto the envelope", "shot": "detail", "transition": "insert", "energy": "tense"},
            ],
        })
        with mock.patch("faceless_video_generator.script_writer._complete_with_retry", return_value=raw):
            plan = plan_cinematic_storyboard(sentences, provider="anthropic", model="claude-sonnet-4-6")
        self.assertEqual(len(plan["scenes"]), 2)
        self.assertEqual(plan["scenes"][0]["shot"], "tracking")

    def test_anthropic_provider_parses_message_content(self):
        from faceless_video_generator.online_ai import generate_text
        response = {"content": [{"type": "text", "text": "hello from claude"}]}

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode()

        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=True), \
             mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertEqual(generate_text("hi", provider="anthropic", model="claude-sonnet-4-6"), "hello from claude")

class FallbackTest(unittest.TestCase):
    def test_transient_failure_falls_back_to_local_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            with mock.patch.object(RunwayVideoProvider, "generate", side_effect=VideoProviderError("timeout")):
                self.assertIsNone(gen._select_motion_video(index=0, sentence="Hi.", image=_image(tmp), duration=3))

    def test_fatal_failure_stops_the_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            with mock.patch.object(RunwayVideoProvider, "generate", side_effect=VideoProviderError("bad key", fatal=True)):
                with self.assertRaises(RenderError):
                    gen._select_motion_video(index=0, sentence="Hi.", image=_image(tmp), duration=3)

    def test_scene_without_image_can_use_runway_text_to_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)

            seen = []
            def fake(self, *, prompt, image, output, duration, retries=2):
                seen.append(image)
                _make_clip(gen.ffmpeg, output, 3)
                with output.open("ab") as handle:
                    handle.write(b"\0" * 30_000)
                return output

            with mock.patch.object(RunwayVideoProvider, "generate", fake):
                result = gen._select_motion_video(index=0, sentence="Hi.", image=None, duration=3)
            self.assertIsNotNone(result)
            self.assertTrue(result.exists())
            self.assertEqual(seen, [None])

    def test_broken_download_is_deleted_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)

            def broken(self, *, prompt, image, output, duration, retries=2):
                output.write_bytes(b"x" * 100)
                return output

            with mock.patch.object(RunwayVideoProvider, "generate", broken):
                self.assertIsNone(gen._select_motion_video(index=0, sentence="Hi.", image=_image(tmp), duration=3))
            self.assertEqual(list(gen.config.work_dir.glob("motion-*.mp4")), [])


class WebUiGuardTest(unittest.TestCase):
    def test_creator_pro_without_key_is_refused_before_rendering(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "RUNWAYML_API_SECRET"):
                webui.start_job({"script": "Hello world.", "video_mode": "cinematic", "style": "photo"})


if __name__ == "__main__":
    unittest.main()
