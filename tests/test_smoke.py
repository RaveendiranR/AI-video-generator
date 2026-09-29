"""End-to-end render with fake TTS and fake images, without network access."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from faceless_video_generator.config import VideoConfig
from faceless_video_generator.pipeline import VideoGenerator


class FakeGenerator(VideoGenerator):
    def _synthesize(self, text, output):
        seconds = max(1.0, len(text.split()) / 2.8)
        subprocess.run(
            [
                self.ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:duration={seconds}",
                "-ar",
                "44100",
                str(output),
            ],
            check=True,
        )

    def _generate_image(self, prompt, output, seed):
        subprocess.run(
            [
                self.ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1024x1024:rate=1:duration=1",
                "-frames:v",
                "1",
                str(output),
            ],
            check=True,
        )


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class SmokeTest(unittest.TestCase):
    def test_render_with_motion_and_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.txt"
            script.write_text(
                "Honey never spoils. It can last for thousands of years. Bacteria cannot survive in it.",
                encoding="utf-8",
            )
            config = VideoConfig(
                script=script,
                width=360,
                height=640,
                fps=24,
                preset="ultrafast",
                crf=30,
                smart_prompts=False,
                image_delay=0,
            )
            output = FakeGenerator(config).render()
            self.assertTrue(output.exists() and output.stat().st_size > 10_000)
            self.assertTrue((script.parent / "work" / "captions.ass").exists())


if __name__ == "__main__":
    unittest.main()