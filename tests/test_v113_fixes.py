"""Regression tests for bugs found in v1.13 (Claude director, Runway retries, final QA)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from faceless_video_generator import video_generation as vg
from faceless_video_generator.config import VideoConfig
from faceless_video_generator.director import build_prompt, SHOT_LIBRARY
from faceless_video_generator.pipeline import RenderError, VideoGenerator
from faceless_video_generator.script_writer import plan_cinematic_storyboard


def _generator(tmp, **overrides):
    script = Path(tmp) / "script.txt"
    script.write_text("Hello there. General Kenobi is here.", encoding="utf-8")
    config = VideoConfig(script=script, width=160, height=284, fps=12, preset="ultrafast", crf=40, **overrides).resolve()
    config.work_dir.mkdir(parents=True, exist_ok=True)
    return VideoGenerator(config)


class ClassifyErrorTest(unittest.TestCase):
    def test_digits_inside_ids_do_not_look_like_http_codes(self):
        error = vg.classify_error(RuntimeError("Task 4f2a-1403-9c failed: server timeout"))
        self.assertFalse(error.fatal)
        self.assertTrue(error.retryable)

    def test_status_code_attribute_wins(self):
        class Boom(Exception):
            status_code = 401
        self.assertTrue(vg.classify_error(Boom("nope")).fatal)
        Boom.status_code = 402
        self.assertTrue(vg.classify_error(Boom("nope")).fatal)
        Boom.status_code = 429
        self.assertTrue(vg.classify_error(Boom("slow down")).retryable)
        Boom.status_code = 400
        error = vg.classify_error(Boom("bad request"))
        self.assertFalse(error.fatal)
        self.assertFalse(error.retryable)

    def test_moderation_rejections_are_not_retried(self):
        self.assertFalse(vg.classify_error(RuntimeError("Task failed: content moderation")).retryable)


class RunwayEndpointTest(unittest.TestCase):
    def _run(self, image, client):
        fake = types.ModuleType("runwayml")
        fake.RunwayML = lambda: client
        with tempfile.TemporaryDirectory() as tmp:
            picture = None
            if image:
                picture = Path(tmp) / "i.png"
                picture.write_bytes(b"x")
            with mock.patch.dict(sys.modules, {"runwayml": fake}), \
                 mock.patch.dict(os.environ, {"RUNWAYML_API_SECRET": "k"}), mock.patch("time.sleep"):
                return vg.RunwayVideoProvider().generate(prompt="p", image=picture, output=Path(tmp) / "o.mp4",
                                                         duration=3, retries=2)

    def test_no_image_uses_text_to_video(self):
        used = []

        class Client:
            class image_to_video:
                @staticmethod
                def create(**kw):
                    used.append("image_to_video")
                    raise RuntimeError("must not be called")

            class text_to_video:
                @staticmethod
                def create(**kw):
                    used.append("text_to_video")
                    assert "prompt_image" not in kw
                    raise RuntimeError("Task failed: content moderation")

        with self.assertRaises(vg.VideoProviderError):
            self._run(False, Client)
        self.assertEqual(used, ["text_to_video"])  # and a rejected prompt is tried exactly once

    def test_transient_errors_are_retried_then_succeed(self):
        attempts = []

        class Task:
            output = ["https://example.invalid/clip.mp4"]

        class Client:
            class image_to_video:
                @staticmethod
                def create(**kw):
                    attempts.append(1)
                    if len(attempts) < 3:
                        raise RuntimeError("503 service unavailable")
                    return types.SimpleNamespace(wait_for_task_output=lambda: Task)

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"\0" * 20_000

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            result = self._run(True, Client)
        self.assertEqual(len(attempts), 3)
        self.assertTrue(str(result).endswith("o.mp4"))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FinalValidationTest(unittest.TestCase):
    def test_small_but_valid_video_passes(self):
        """Regression: a flat-colour 3 s clip is ~5 KB and was rejected by a 50 KB floor after a full render."""
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            out = Path(tmp) / "o.mp4"
            subprocess.run([gen.ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=160x284:r=12:d=3",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "3", "-c:v", "libx264", "-crf", "40",
                            "-c:a", "aac", str(out)], check=True)
            self.assertLess(out.stat().st_size, 50_000)
            gen._validate_final_video(out, expected_duration=3.0)

    def test_truncated_video_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp)
            out = Path(tmp) / "o.mp4"
            subprocess.run([gen.ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=160x284:r=12:d=2",
                            "-c:v", "libx264", str(out)], check=True)
            with self.assertRaises(RenderError):
                gen._validate_final_video(out, expected_duration=10.0)


class StoryboardCacheTest(unittest.TestCase):
    SENTENCES = ["He enters the station.", "He sees an envelope."]

    def test_fallback_prompts_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp, use_ai_images=True)
            plan = {"storyboard": {}, "prompts": list(self.SENTENCES)}  # every scene fell back to narration
            with mock.patch.dict(os.environ, {"POLLINATIONS_API_KEY": "k"}, clear=True), \
                 mock.patch("faceless_video_generator.pipeline.write_storyboard", return_value=plan):
                gen._load_visual_prompts(self.SENTENCES, "hash")
            self.assertFalse((gen.config.work_dir / "visual_prompts.json").exists())

    def test_script_is_not_sent_to_an_ai_when_nothing_uses_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = _generator(tmp, use_ai_images=False)  # local motion, no AI images
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret"}), \
                 mock.patch("faceless_video_generator.pipeline.write_storyboard") as storyboard, \
                 mock.patch("faceless_video_generator.pipeline.plan_cinematic_storyboard") as director:
                self.assertEqual(gen._load_visual_prompts(self.SENTENCES, "hash"), self.SENTENCES)
            storyboard.assert_not_called()
            director.assert_not_called()

    def test_runway_cache_is_not_reused_from_a_non_director_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = _generator(tmp, use_ai_images=True)
            plan = {"storyboard": {"visual_bible": {}}, "prompts": ["a", "b"]}
            with mock.patch.dict(os.environ, {"POLLINATIONS_API_KEY": "k"}, clear=True), \
                 mock.patch("faceless_video_generator.pipeline.write_storyboard", return_value=plan):
                local._load_visual_prompts(self.SENTENCES, "hash")
            self.assertTrue((local.config.work_dir / "visual_prompts.json").exists())
            runway = _generator(tmp, use_ai_images=True, video_provider="runway")
            scenes = {"storyboard": {"visual_bible": {"subjects": ["x"]}},
                      "scenes": [{"visual": "v1", "beat": "b1"}, {"visual": "v2", "beat": "b2"}]}
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True), \
                 mock.patch("faceless_video_generator.pipeline.plan_cinematic_storyboard", return_value=scenes) as director:
                prompts = runway._load_visual_prompts(self.SENTENCES, "hash")
            director.assert_called_once()
            self.assertEqual(prompts, ["v1", "v2"])


class DirectorBibleTest(unittest.TestCase):
    RAW = json.dumps({
        "story_summary": "s",
        "visual_bible": {"subjects": ["courier in red jacket"], "locations": ["night market"],
                         "continuity": ["rainy night"], "palette": "teal"},
        "scenes": [{"visual": "v", "beat": "b"}],
    })

    def test_continuity_reaches_the_runway_prompt(self):
        """Regression: the director used keys the prompt builder never read, so continuity was silently dropped."""
        with mock.patch("faceless_video_generator.script_writer._complete_with_retry", return_value=self.RAW) as call:
            plan = plan_cinematic_storyboard(["A courier runs."], provider="anthropic", model="m")
        self.assertEqual(call.call_count, 1)  # no second, wasted bible-only request
        prompt = build_prompt(visual="v", sentence="s", bible=plan["storyboard"]["visual_bible"], plan=SHOT_LIBRARY[0])
        for text in ("red jacket", "night market", "rainy night"):
            self.assertIn(text, prompt)


if __name__ == "__main__":
    unittest.main()
