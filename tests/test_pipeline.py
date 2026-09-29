import tempfile
import unittest
from pathlib import Path

from faceless_video_generator.config import VideoConfig
from faceless_video_generator.pipeline import srt_time, split_sentences


class PipelineHelpersTest(unittest.TestCase):
    def test_split_sentences_normalizes_whitespace(self):
        self.assertEqual(
            split_sentences("First sentence.\nSecond sentence!  Third?"),
            ["First sentence.", "Second sentence!", "Third?"],
        )

    def test_split_sentences_does_not_drop_unpunctuated_tail(self):
        self.assertEqual(split_sentences("A sentence without punctuation"), ["A sentence without punctuation"])

    def test_srt_time_handles_hours_and_rounding(self):
        self.assertEqual(srt_time(3723.456), "01:02:03,456")
        self.assertEqual(srt_time(0.9996), "00:00:01,000")

    def test_config_resolves_paths_relative_to_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "nested" / "script.txt"
            config = VideoConfig(script=script).resolve()
            self.assertEqual(config.output, script.parent / "output.mp4")
            self.assertEqual(config.work_dir, script.parent / "work")


class GroupSentencesTest(unittest.TestCase):
    def test_groups_short_sentences(self):
        from faceless_video_generator.pipeline import group_sentences

        sentences = ["Honey never spoils.", "It lasts for thousands of years.", "Bacteria cannot survive in it.", "Amazing."]
        scenes = group_sentences(sentences, 8)
        self.assertEqual(" ".join(scenes), " ".join(sentences))
        self.assertLess(len(scenes), len(sentences))

    def test_zero_disables_grouping_and_tiny_tail_is_merged(self):
        from faceless_video_generator.pipeline import group_sentences

        self.assertEqual(group_sentences(["A b.", "C d."], 0), ["A b.", "C d."])
        merged = group_sentences(["One two three four five six.", "Seven."], 6)
        self.assertEqual(merged, ["One two three four five six. Seven."])


if __name__ == "__main__":
    unittest.main()
