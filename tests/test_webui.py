import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from faceless_video_generator import webui
from faceless_video_generator.cli import build_parser
from faceless_video_generator.motion.cli import build_parser as motion_parser


class BuildCommandTest(unittest.TestCase):
    def parse(self, opts):
        cmd = webui.build_command(opts, Path("script.txt"))
        return cmd, build_parser().parse_args(cmd[cmd.index("faceless_video_generator") + 1:])

    def test_flags_are_accepted_by_the_real_cli_parser(self):
        for quality in ("fast", "balanced", "best"):
            for orientation in ("portrait", "landscape"):
                self.parse({"quality": quality, "orientation": orientation, "music": False,
                            "ai_images": False, "motion": False})

    def test_size_and_voice(self):
        _, args = self.parse({"quality": "fast", "orientation": "landscape", "voice": "not-a-voice"})
        self.assertEqual((args.width, args.height), (1280, 720))
        self.assertEqual(args.voice, "en-US-AndrewNeural")
        self.assertTrue(args.no_motion)


class PhotoCommandUnchangedTest(unittest.TestCase):
    """The photo video command (voice, AI images, zoom/pan) must stay exactly as it was before motion videos existed."""

    def test_default_photo_command_is_identical_to_v1_6(self):
        cmd = webui.build_command({}, Path("script.txt"))
        self.assertEqual(cmd[1:], [
            "-u", "-m", "faceless_video_generator", "--script", "script.txt", "--output", "output.mp4", "--force",
            "--width", "1080", "--height", "1920", "--voice", "en-US-AndrewNeural",
            "--preset", "veryfast", "--crf", "21", "--min-scene-words", "18"])

    def test_caps_off_is_the_only_new_photo_flag(self):
        self.assertIn("--no-caps", webui.build_command({"caps": False}, Path("s.txt")))
        self.assertNotIn("--no-caps", webui.build_command({"caps": True}, Path("s.txt")))


class MotionCommandTest(unittest.TestCase):
    def parse(self, opts, script=Path("script.txt")):
        cmd = webui.build_command({"style": "motion", **opts}, script)
        self.assertEqual(cmd[3], "faceless_video_generator.motion")
        return cmd, motion_parser().parse_args(cmd[4:])

    def test_every_option_combination_is_accepted_by_the_motion_parser(self):
        for quality in ("fast", "balanced", "best"):
            for orientation in ("portrait", "landscape"):
                for spec in (True, False):
                    for plan in ("smart", "offline"):
                        self.parse({"quality": quality, "orientation": orientation, "spec": spec, "plan": plan,
                                    "narrate": False, "music": False, "caps": False, "tag": "-x"})

    def test_voice_is_shared_with_photo_videos(self):
        _, args = self.parse({"voice": "en-GB-RyanNeural"})
        self.assertTrue(args.narrate)
        self.assertEqual((args.voice, args.voice_rate, args.tts_provider), ("en-GB-RyanNeural", "+8%", "edge-tts"))
        _, args = self.parse({"voice": "not-a-voice"})
        self.assertEqual(args.voice, "en-US-AndrewNeural")

    def test_script_planning_and_spec_modes(self):
        _, smart = self.parse({})
        self.assertTrue(smart.ai_plan)
        self.assertEqual(smart.script, Path("script.txt"))
        _, offline = self.parse({"plan": "offline"})
        self.assertFalse(offline.ai_plan)
        _, given = self.parse({"spec": True})
        self.assertEqual(given.spec, Path("spec.json"))
        self.assertIsNone(given.script)

    def test_accent_size_and_audio_flags(self):
        _, args = self.parse({"accent": "#3366FF", "quality": "fast", "orientation": "landscape", "music": True, "caps": False})
        self.assertEqual((args.accent, args.width, args.height, args.fps), ("#3366FF", 1280, 720, 24))
        self.assertTrue(args.auto_music)
        self.assertTrue(args.no_caps)
        _, args = self.parse({"accent": "red; rm -rf /", "narrate": False})
        self.assertEqual(args.accent, webui.DEFAULT_ACCENT)
        self.assertFalse(args.narrate)


class MotionProgressTest(unittest.TestCase):
    def test_lines_fold_into_one_percentage(self):
        webui.JOB.pct, webui.JOB.phase = None, ""
        webui._motion_progress("INFO Planning scenes with the text model (part 2 of 4)")
        self.assertEqual((webui.JOB.phase, webui.JOB.pct), ("Planning scenes", 2))
        webui._motion_progress("INFO [3/4] narrating: hello")
        self.assertEqual((webui.JOB.phase, webui.JOB.pct), ("Recording the voice", 10 + 25 * 2 // 4))
        webui._motion_progress("INFO Rendering frames: 100%")
        self.assertEqual((webui.JOB.phase, webui.JOB.pct), ("Drawing scenes", 98))
        webui._motion_progress("INFO Rendering frames: 10%")  # never goes backwards
        self.assertEqual(webui.JOB.pct, 98)
        webui.JOB.pct, webui.JOB.phase = None, ""


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(webui, "ROOT", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        fake = [sys.executable, "-c",
                "print('INFO Rendering 2 scenes');print('INFO [1] a');print('INFO [2] b');"
                "open('output.mp4','wb').write(b'0123456789')"]
        self._real_build = webui.build_command
        p2 = mock.patch.object(webui, "build_command", lambda opts, script: fake)
        p2.start()
        self.addCleanup(p2.stop)
        webui.JOB.status, webui.JOB.dir = "idle", None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webui.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.tmp.cleanup)

    def post(self, path, data, header=True):
        headers = {"Content-Type": "application/json"}
        if header:
            headers["X-Requested-With"] = "faceless-ui"
        req = urllib.request.Request(self.base + path, json.dumps(data).encode(), headers)
        return urllib.request.urlopen(req)

    def test_page_and_forbidden_without_header(self):
        self.assertIn(b"Faceless Video Maker", urllib.request.urlopen(self.base + "/").read())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/start", {"script": "Hi."}, header=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_static_files_are_served_and_confined(self):
        page = urllib.request.urlopen(self.base + "/")
        self.assertIn("default-src 'self'", page.headers["Content-Security-Policy"])
        self.assertIn(b'src="/js/main.js"', page.read())
        js = urllib.request.urlopen(self.base + "/js/main.js")
        self.assertTrue(js.headers["Content-Type"].startswith("text/javascript"))
        self.assertTrue(urllib.request.urlopen(self.base + "/styles.css").headers["Content-Type"].startswith("text/css"))
        for bad in ("/js/nope.js", "/../webui.py", "/%2e%2e/webui.py", "/js/", "/api/nope"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(self.base + bad)
            self.assertEqual(ctx.exception.code, 404, bad)

    def test_every_module_the_page_imports_exists(self):
        import re
        web = Path(webui.__file__).parent / "web" / "js"
        for source in web.glob("*.js"):
            for name in re.findall(r'from "\./([\w-]+\.js)"', source.read_text(encoding="utf-8")):
                self.assertTrue((web / name).is_file(), f"{source.name} imports missing {name}")

    def test_config_and_status_timing(self):
        config = json.loads(urllib.request.urlopen(self.base + "/api/config").read())
        self.assertEqual(config["voices"], webui.VOICES)
        self.assertEqual(config["default_accent"], webui.DEFAULT_ACCENT)
        self.assertIn("elapsed", json.loads(urllib.request.urlopen(self.base + "/api/status").read()))

    def test_foreign_host_header_is_refused(self):
        for path in ("/", "/api/status"):
            req = urllib.request.Request(self.base + path, headers={"Host": "evil.example:8765"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
        ok = urllib.request.Request(self.base + "/api/status", headers={"Host": "localhost:8765"})
        self.assertEqual(urllib.request.urlopen(ok).status, 200)

    def test_empty_script_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/start", {"script": "  "})
        self.assertEqual(ctx.exception.code, 400)

    def test_job_progress_and_ranged_video(self):
        self.post("/api/start", {"script": "Hello world."})
        for _ in range(60):
            status = json.loads(urllib.request.urlopen(self.base + "/api/status").read())
            if status["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(status["status"], "done")
        self.assertEqual((status["total"], status["done"], status["video"]), (2, 2, True))
        req = urllib.request.Request(self.base + "/output.mp4", headers={"Range": "bytes=2-5"})
        resp = urllib.request.urlopen(req)
        self.assertEqual((resp.status, resp.read()), (206, b"2345"))
        self.assertEqual(resp.headers["Content-Range"], "bytes 2-5/10")

    def test_demo_preview_and_offline_plan(self):
        demo = json.loads(self.post("/api/demo", {}).read())
        self.assertEqual(len(demo["spec"]["scenes"]), 5)
        self.assertIn("loops", demo["script"])
        shown = json.loads(self.post("/api/preview", {"spec": json.dumps(demo["spec"]), "orientation": "landscape"}).read())
        self.assertEqual([s["type"] for s in shown["scenes"]], ["hook", "kinetic", "steps", "chart", "outro"])
        self.assertTrue(all(s["image"].startswith("data:image/png;base64,") for s in shown["scenes"]))
        # the plan's own accent survives unless the page sends one
        demo["spec"]["style"]["accent"] = "#3366FF"
        kept = json.loads(self.post("/api/preview", {"spec": json.dumps(demo["spec"]), "accent": ""}).read())
        self.assertEqual(kept["spec"]["style"]["accent"], "#3366FF")
        over = json.loads(self.post("/api/preview", {"spec": json.dumps(demo["spec"]), "accent": "#00AA00"}).read())
        self.assertEqual(over["spec"]["style"]["accent"], "#00AA00")
        planned = json.loads(self.post("/api/plan", {
            "script": "Sleep matters. Adults need seven to nine hours. Skip it and focus drops by 30%. Protect your sleep.",
            "plan": "offline", "tag": "sleep", "accent": "#3366FF", "caps": False}).read())
        self.assertEqual(planned["spec"]["style"]["accent"], "#3366FF")
        self.assertEqual(planned["warnings"], [])
        self.assertEqual(planned["spec"]["scenes"][0]["type"], "hook")
        self.assertIn("chart", [s["type"] for s in planned["spec"]["scenes"]])

    def test_plan_and_preview_errors_are_readable(self):
        for path, body, text in (
            ("/api/plan", {"script": " "}, "Add a script"),
            ("/api/preview", {"spec": "{nope"}, "not valid JSON"),
            ("/api/preview", {"spec": json.dumps({"scenes": [{"type": "chart"}]})}, "scene 1 (chart)"),
        ):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(path, body)
            self.assertEqual(ctx.exception.code, 400)
            self.assertIn(text, json.loads(ctx.exception.read())["error"])

    def test_smart_plan_falls_back_offline_when_the_model_is_unreachable(self):
        def down(prompt):
            raise RuntimeError("no internet")

        with mock.patch.object(webui, "_text_completer", lambda: down):
            data = json.loads(self.post("/api/plan", {"script": "Hello there world. This is fine.", "plan": "smart"}).read())
        self.assertEqual([s["type"] for s in data["spec"]["scenes"]], ["hook", "outro"])
        self.assertIn("offline planner", data["warnings"][0])

    def test_motion_job_takes_a_plan_without_a_script(self):
        captured = {}
        real = webui.subprocess.Popen

        def fake(cmd, **kw):
            captured["cmd"], captured["cwd"] = cmd, kw["cwd"]
            return real([sys.executable, "-c", "open('output.mp4','wb').write(b'x')"], **kw)

        demo = json.loads(self.post("/api/demo", {}).read())
        webui.build_command = self._real_build
        with mock.patch.object(webui.subprocess, "Popen", fake):
            self.post("/api/start", {"style": "motion", "script": "", "spec": json.dumps(demo["spec"]), "accent": "#3366FF"})
        for _ in range(60):
            if json.loads(urllib.request.urlopen(self.base + "/api/status").read())["status"] != "running":
                break
            time.sleep(0.1)
        saved = json.loads((Path(captured["cwd"]) / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["style"]["accent"], "#3366FF")
        self.assertIn("--spec", captured["cmd"])
        self.assertNotIn("--script", captured["cmd"])
        with self.assertRaises(urllib.error.HTTPError):  # photo videos still need a script
            self.post("/api/start", {"style": "photo", "script": ""})


if __name__ == "__main__":
    unittest.main()
