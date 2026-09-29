import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from faceless_video_generator import script_writer as sw
from faceless_video_generator.config import VideoConfig
from faceless_video_generator.media import CommandError
from faceless_video_generator.pipeline import VideoGenerator, split_sentences


class CleanNarrationTest(unittest.TestCase):
    def test_removes_artifacts_seen_in_a_real_failure(self):
        raw = (
            "Most habits fail early. (13 words)\\n\\nParagraph 4: Science of cue design.\\n\\n"
            "13. Research shows that clear cues outperform vague reminders."
        )
        cleaned = sw.clean_narration(raw)
        self.assertEqual(
            cleaned,
            "Most habits fail early. Research shows that clear cues outperform vague reminders.",
        )

    def test_real_newlines_markdown_and_numbering(self):
        raw = "# Title\n\n**Part 2: Cues**\n1. First idea matters.\n2) Second idea matters too.\n[pause] Done."
        cleaned = sw.clean_narration(raw)
        self.assertNotIn("Title", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("[pause]", cleaned)
        self.assertIn("First idea matters.", cleaned)
        self.assertNotIn("Cues", cleaned)
        self.assertEqual(len(split_sentences(cleaned)), 3)

    def test_plain_text_is_unchanged(self):
        text = "Honey never spoils. It lasts for thousands of years."
        self.assertEqual(sw.clean_narration(text), text)


class LongScriptTest(unittest.TestCase):
    def test_writes_sections_and_cleans_each(self):
        calls = []

        def fake(prompt, **kw):
            calls.append(prompt)
            if "Return ONLY a JSON array" in prompt:
                return json.dumps(["Hook", "A", "B", "C", "Wrap"])
            n = len(calls)
            return f"Paragraph {n}: heading.\\n\\nThis is sentence one of part {n}. (9 words) Sentence two of part {n}."

        with mock.patch.object(sw, "generate_text", fake), mock.patch.object(sw.time, "sleep"):
            text = sw.write_script("habits", seconds=300)
        self.assertEqual(text.count("This is sentence one"), 5)
        self.assertNotIn("Paragraph", text)
        self.assertNotIn("words)", text)
        self.assertNotIn("\\n", text)

    def test_visual_prompt_batches_recover_and_fall_back(self):
        state = {"n": 0}

        def fake(prompt, **kw):
            state["n"] += 1
            count = int(prompt.split("exactly ")[1].split(" strings")[0])
            if state["n"] in (2, 3, 4):  # the middle batch fails all three attempts
                return "not json"
            return json.dumps([f"photo {state['n']}-{i}" for i in range(count)])

        sentences = [f"Sentence {i}." for i in range(24)]
        with mock.patch.object(sw, "generate_text", fake), mock.patch.object(sw.time, "sleep"):
            out = sw.write_visual_prompts(sentences)
        self.assertEqual(len(out), 24)
        self.assertEqual(sum(a == b for a, b in zip(out, sentences)), 8)

    def test_storyboard_reads_the_whole_narration_before_scene_prompts(self):
        analysis_calls = []

        def fake_analysis(prompt, *args, **kwargs):
            analysis_calls.append(prompt)
            return json.dumps(
                {
                    "story_summary": "A researcher follows a lost signal.",
                    "visual_bible": {
                        "overall_style": "photorealistic documentary",
                        "color_palette": "slate blue and amber",
                        "lighting": "dawn light",
                        "camera_language": "wide establishing shots and macro details",
                        "recurring_subjects": ["a weathered field notebook"],
                        "recurring_locations": ["a remote mountain station"],
                        "continuity_rules": ["keep the notebook and station consistent"],
                    },
                }
            )

        def fake_scene_prompts(prompt, **kwargs):
            count = int(prompt.split("exactly ")[1].split(" strings")[0])
            return json.dumps([f"shot {index}: mountain station and notebook" for index in range(count)])

        sentences = [
            "The signal begins in a remote valley.",
            "The researcher climbs toward the mountain station.",
            "The notebook reveals the answer at dawn.",
        ]
        with mock.patch.object(sw, "_complete_with_retry", fake_analysis), \
             mock.patch.object(sw, "generate_text", fake_scene_prompts), \
             mock.patch.object(sw.time, "sleep"):
            plan = sw.write_storyboard(sentences, image_style="photorealistic documentary")

        self.assertEqual(len(plan["prompts"]), 3)
        self.assertEqual(len(analysis_calls), 1)
        self.assertIn(sentences[0], analysis_calls[0])
        self.assertIn(sentences[-1], analysis_calls[0])
        self.assertEqual(
            plan["storyboard"]["visual_bible"]["recurring_subjects"],
            ["a weathered field notebook"],
        )


class VoiceRetryTest(unittest.TestCase):
    def test_text_goes_through_file_and_transient_failure_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.txt"
            script.write_text("Hello there.", encoding="utf-8")
            gen = VideoGenerator(VideoConfig(script=script, dry_run=True))
            seen = []

            def flaky(command, **kw):
                seen.append(command)
                self.assertTrue(Path(command[command.index("--file") + 1]).exists())
                if len(seen) < 3:
                    raise CommandError("No audio was received")

            mp3 = Path(tmp) / "out.mp3"
            with mock.patch("faceless_video_generator.pipeline.run_command", flaky), \
                 mock.patch("faceless_video_generator.pipeline.time.sleep"):
                gen._run_edge_tts("Text with 'quotes' and %percent and \\n slashes.", mp3)
            self.assertEqual(len(seen), 3)
            self.assertNotIn("--text", " ".join(seen[0]))
            self.assertFalse(mp3.with_suffix(".txt").exists())


if __name__ == "__main__":
    unittest.main()
