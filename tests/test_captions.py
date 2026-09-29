import unittest

from faceless_video_generator.captions import ass_time, build_ass, chunk_words, timed_chunks


class CaptionTest(unittest.TestCase):
    def test_chunks_are_short_and_lossless(self):
        sentence = "They map the day in minutes, not hours, with a simple list."
        chunks = chunk_words(sentence)
        self.assertTrue(all(len(chunk.split()) <= 4 for chunk in chunks))
        self.assertEqual(" ".join(chunks), sentence)

    def test_timing_covers_scene_without_gaps(self):
        parts = list(timed_chunks("One two three four five six seven eight.", 10.0, 4.0, 0.25))
        self.assertAlmostEqual(parts[0][0], 10.0)
        self.assertAlmostEqual(parts[-1][1], 14.0)
        for first, second in zip(parts, parts[1:]):
            self.assertAlmostEqual(first[1], second[0])

    def test_ass_time(self):
        self.assertEqual(ass_time(3723.456), "1:02:03.46")

    def test_build_ass_escapes_braces_and_uppercases(self):
        text = build_ass([{"sentence": "Hello {world}.", "duration": 2.0}], width=1080, height=1920)
        self.assertIn("HELLO (WORLD).", text)
        self.assertIn("PlayResY: 1920", text)