import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from faceless_video_generator.envfile import load_env


class EnvFileTest(unittest.TestCase):
    def test_reads_keys_and_real_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / ".env"
            file.write_text('# note\nPOLLINATIONS_API_KEY="sk_test"\nexport HF_TOKEN=hf_x\nKEPT=file\nEMPTY=\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"KEPT": "real"}, clear=False):
                os.environ.pop("POLLINATIONS_API_KEY", None)
                os.environ.pop("HF_TOKEN", None)
                names = load_env(file)
                self.assertEqual(sorted(names), ["HF_TOKEN", "POLLINATIONS_API_KEY"])
                self.assertEqual(os.environ["POLLINATIONS_API_KEY"], "sk_test")
                self.assertEqual(os.environ["KEPT"], "real")
                os.environ.pop("POLLINATIONS_API_KEY", None)
                os.environ.pop("HF_TOKEN", None)


class ImageBreakerTest(unittest.TestCase):
    def test_stops_asking_after_three_scenes_in_a_row(self):
        from faceless_video_generator.pipeline import VideoGenerator

        gen = object.__new__(VideoGenerator)
        gen._image_failures, gen._images_disabled = 0, False
        missing = Path("/nonexistent/x.jpg")
        for _ in range(2):
            gen._track_image_result(missing)
        self.assertFalse(gen._images_disabled)
        with tempfile.NamedTemporaryFile() as ok:
            gen._track_image_result(Path(ok.name))  # a success resets the count
            self.assertEqual(gen._image_failures, 0)
        for _ in range(3):
            gen._track_image_result(missing)
        self.assertTrue(gen._images_disabled)


if __name__ == "__main__":
    unittest.main()
