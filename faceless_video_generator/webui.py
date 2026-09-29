"""Local web page for creating videos without the command line.

Run:  python -m faceless_video_generator.webui   (opens http://127.0.0.1:8765)
Two video styles: photo videos (AI images with zoom/pan) and chart & diagram motion-graphics videos.
The page itself needs only the standard library (motion graphics also use Pillow). Rendering runs in a background process.

The page is a small TypeScript app. Its source is in ``frontend/src`` and the compiled JavaScript ships in
``faceless_video_generator/web`` (run ``npm run build`` in ``frontend`` after editing it), so end users need no Node.js.
"""
from __future__ import annotations

import argparse
import base64
import copy
import html
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path.cwd() / "webui_jobs"
WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
}
# The page only ever talks to this server, so it can be locked down tightly.
CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
VOICES = [
    "en-US-AndrewNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-JennyNeural",
    "en-GB-RyanNeural", "en-IN-PrabhatNeural", "en-IN-NeerjaNeural",
]
PRESETS = {
    "fast": ["--no-motion", "--preset", "veryfast", "--crf", "23", "--fps", "24",
             "--min-scene-words", "24", "--image-retries", "2", "--image-delay", "5"],
    "balanced": ["--preset", "veryfast", "--crf", "21", "--min-scene-words", "18"],
    "best": [],
}
MOTION_PRESETS = {
    "fast": ["--preset", "veryfast", "--crf", "23", "--fps", "24"],
    "balanced": ["--preset", "veryfast", "--crf", "21"],
    "best": [],
}
DEFAULT_ACCENT = "#E8630A"
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
PREVIEW_SIZE = (360, 640)  # portrait thumbnail; landscape swaps the two


class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.log: list[str] = []
        self.status = "idle"
        self.dir: Path | None = None
        self.total = 0
        self.done = 0
        self.pct: int | None = None  # motion videos report a 0-100 figure; photo videos use done/total
        self.phase = ""
        self.started: float | None = None
        self.ended: float | None = None

    def elapsed(self) -> int:
        if self.started is None:
            return 0
        return int((self.ended or time.time()) - self.started)


JOB = Job()


def _is_motion(opts: dict) -> bool:
    return opts.get("style") == "motion"


def _size(opts: dict, quality: str) -> tuple[int, int]:
    width, height = (720, 1280) if quality == "fast" else (1080, 1920)
    return (height, width) if opts.get("orientation") == "landscape" else (width, height)


def _accent(opts: dict) -> str:
    value = str(opts.get("accent") or "")
    return value if HEX_COLOR.fullmatch(value) else DEFAULT_ACCENT


def build_command(opts: dict, script: Path) -> list[str]:
    quality = opts.get("quality") if opts.get("quality") in PRESETS else "balanced"
    width, height = _size(opts, quality)
    voice = opts.get("voice") if opts.get("voice") in VOICES else VOICES[0]
    if _is_motion(opts):
        return _motion_command(opts, script, quality, width, height, voice)
    cmd = [sys.executable, "-u", "-m", "faceless_video_generator", "--script", str(script),
           "--output", "output.mp4", "--force", "--width", str(width), "--height", str(height),
           "--voice", voice, *PRESETS[quality]]
    if not opts.get("music", True):
        cmd.append("--no-music")
    if not opts.get("ai_images", True):
        cmd.append("--no-ai-images")
    if not opts.get("motion", True) and "--no-motion" not in cmd:
        cmd.append("--no-motion")
    if opts.get("video_mode") == "cinematic":
        cmd += ["--video-provider", "runway", "--video-model", "gen4.5",
                "--director-provider", str(opts.get("director") or "auto"),
                "--director-model", str(opts.get("director_model") or "claude-sonnet-4-6")]
    if opts.get("caps") is False:
        cmd.append("--no-caps")
    return cmd


def _motion_command(opts: dict, script: Path, quality: str, width: int, height: int, voice: str) -> list[str]:
    """Chart & diagram video. Same voices and narration engine as photo videos; only the visuals differ."""
    cmd = [sys.executable, "-u", "-m", "faceless_video_generator.motion"]
    if opts.get("spec"):  # scene plan written next to the script by start_job
        cmd += ["--spec", str(script.parent / "spec.json")]
    else:
        cmd += ["--script", str(script), f"--tag={str(opts.get('tag') or 'KEY IDEA').strip()[:40] or 'KEY IDEA'}"]
        if opts.get("plan") != "offline":
            cmd.append("--ai-plan")
    cmd += ["--output", "output.mp4", "--force", "--width", str(width), "--height", str(height),
            f"--accent={_accent(opts)}", *MOTION_PRESETS[quality]]
    if opts.get("narrate", True):
        cmd += ["--narrate", "--voice", voice]
    if opts.get("music", True):
        cmd.append("--auto-music")
    if opts.get("caps") is False:
        cmd.append("--no-caps")
    return cmd


def parse_spec(raw, opts: dict) -> dict:
    """Validate a scene plan (JSON text or object) and apply the page's accent colour."""
    from .motion import normalize_spec

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ValueError(f"The scene plan is not valid JSON: {exc}") from exc
    spec = normalize_spec(data, uppercase=opts.get("caps") is not False)
    if HEX_COLOR.fullmatch(str(opts.get("accent") or "")):
        spec["style"]["accent"] = opts["accent"]
    return spec


def _text_completer():
    from .script_writer import _complete_with_retry

    return lambda prompt: _complete_with_retry(prompt, "pollinations", "openai", os.getenv("HF_TOKEN"), attempts=2)


def plan_scenes(opts: dict) -> dict:
    """Turn the script into a scene plan: the AI reads it (or quick offline rules) and picks each visual."""
    from .motion import plan_script

    script = str(opts.get("script") or "").strip()
    if not script:
        raise ValueError("Add a script first.")
    warnings: list[str] = []
    tag = str(opts.get("tag") or "KEY IDEA").strip()[:40] or "KEY IDEA"
    spec = plan_script(
        script, None if opts.get("plan") == "offline" else _text_completer(), tag=tag, accent=_accent(opts),
        uppercase=opts.get("caps") is not False, on_warning=warnings.append,
    )
    return {"spec": spec, "warnings": warnings}


def preview_scenes(opts: dict) -> dict:
    """Validate the (possibly hand-edited) plan and draw one thumbnail per scene."""
    from PIL import Image  # noqa: F401  (motion graphics need Pillow)

    from .motion.render import build_context, build_themes, render_frame

    spec = parse_spec(opts.get("spec"), opts)
    width, height = PREVIEW_SIZE
    if opts.get("orientation") == "landscape":
        width, height = height, width
    ctx, themes, scenes = build_context(width, height), build_themes(spec), []
    for scene in spec["scenes"]:
        buffer = io.BytesIO()
        render_frame(scene, scene["duration"] * 0.9, ctx, themes).save(buffer, "PNG", optimize=True)
        scenes.append({"type": scene["type"], "duration": scene["duration"],
                       "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()})
    return {"spec": spec, "scenes": scenes}


def demo_plan() -> dict:
    from .motion import DEMO_SPEC, normalize_spec

    spec = normalize_spec(copy.deepcopy(DEMO_SPEC))
    return {"spec": spec, "script": " ".join(sc["narration"] for sc in spec["scenes"] if sc["narration"])}


def start_job(opts: dict) -> None:
    script = str(opts.get("script") or "").strip()
    spec_text = ""
    if _is_motion(opts) and str(opts.get("spec") or "").strip():
        spec_text = json.dumps(parse_spec(opts["spec"], opts), indent=2, ensure_ascii=False)
    elif not script:
        raise ValueError("Add a script first.")
    if not _is_motion(opts) and opts.get("video_mode") == "cinematic" and opts.get("motion", True):
        if not os.getenv("RUNWAYML_API_SECRET"):
            raise ValueError(
                "Creator Pro needs RUNWAYML_API_SECRET (add it to your .env file), "
                "or switch AI video creation back to Local."
            )
    with JOB.lock:
        if JOB.status == "running":
            raise ValueError("A video is already rendering.")
        if opts.get("resume") and JOB.dir and JOB.dir.exists():
            folder = JOB.dir
        else:
            folder = ROOT / time.strftime("%Y%m%d-%H%M%S")
            folder.mkdir(parents=True, exist_ok=True)
        (folder / "script.txt").write_text(script + "\n", encoding="utf-8")
        if spec_text:
            (folder / "spec.json").write_text(spec_text + "\n", encoding="utf-8")
        else:
            (folder / "spec.json").unlink(missing_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
        JOB.dir, JOB.log, JOB.total, JOB.done, JOB.status = folder, [], 0, 0, "running"
        JOB.pct, JOB.phase = None, ""
        JOB.started, JOB.ended = time.time(), None
        JOB.proc = subprocess.Popen(
            build_command({**opts, "spec": bool(spec_text)}, folder / "script.txt"), cwd=folder, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        threading.Thread(target=_pump, args=(JOB.proc, folder), daemon=True).start()


def _pump(proc: subprocess.Popen, folder: Path) -> None:
    try:
        for line in proc.stdout or []:
            line = line.rstrip()
            with JOB.lock:
                JOB.log = (JOB.log + [line])[-400:]
                match = re.search(r"Rendering (\d+) scenes", line)
                if match:
                    JOB.total = int(match.group(1))
                match = re.match(r"\w+ \[(\d+)\]", line)
                if match:
                    JOB.done = max(JOB.done, int(match.group(1)))
                _motion_progress(line)
    finally:
        if proc.stdout:
            proc.stdout.close()
    code = proc.wait()
    with JOB.lock:
        JOB.ended = time.time()
        if JOB.status != "cancelled":
            JOB.status = "done" if code == 0 and (folder / "output.mp4").exists() else "error"


def _motion_progress(line: str) -> None:
    """Chart & diagram videos log planning, voice and frame progress; fold it into one 0-100 figure."""
    for pattern, phase, base, span in (
        (r"Planning scenes with the text model \(part (\d+) of (\d+)\)", "Planning scenes", 0, 10),
        (r"\[(\d+)/(\d+)\] narrating", "Recording the voice", 10, 25),
    ):
        match = re.match(r"\w+ " + pattern, line)
        if match:
            part, whole = int(match.group(1)), max(1, int(match.group(2)))
            JOB.phase, JOB.pct = phase, max(JOB.pct or 0, base + span * (part - 1) // whole)
            return
    match = re.match(r"\w+ Rendering frames: (\d+)%", line)
    if match:
        JOB.phase, JOB.pct = "Drawing scenes", max(JOB.pct or 0, 35 + int(match.group(1)) * 63 // 100)


def cancel_job() -> None:
    with JOB.lock:
        proc = JOB.proc
        if JOB.status != "running" or proc is None:
            return
        JOB.status = "cancelled"
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def fetch_link(url: str) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Use a full http(s) link.")
    doc = re.match(r"https://docs\.google\.com/document/d/([\w-]+)", url)
    if doc:
        url = f"https://docs.google.com/document/d/{doc.group(1)}/export?format=txt"
    request = urllib.request.Request(url, headers={"User-Agent": "faceless-video-generator-ui"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw, kind = response.read(2_000_000), response.headers.get("Content-Type", "")
    text = raw.decode("utf-8", errors="replace")
    if "html" in kind.lower() or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _host_ok(self) -> bool:
        """Refuse requests whose Host header is not this computer (blocks DNS-rebinding attacks on the local page)."""
        host = self.headers.get("Host")
        if host is None:
            return True
        try:
            return urllib.parse.urlsplit("//" + host).hostname in LOCAL_HOSTS
        except ValueError:
            return False

    def _json(self, data: dict, code: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        """Serve the compiled page (index.html, styles.css, js/*.js) from the web folder, and nothing outside it."""
        name = "index.html" if path == "/" else path.lstrip("/")
        file = (WEB_DIR / name).resolve()
        kind = STATIC_TYPES.get(file.suffix)
        if kind is None or not file.is_file() or not file.is_relative_to(WEB_DIR.resolve()):
            return self.send_error(404)
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-cache")
        if file.suffix == ".html":
            self.send_header("Content-Security-Policy", CSP)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._host_ok():
            return self.send_error(403)
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/config":
            self._json({"voices": VOICES, "default_accent": DEFAULT_ACCENT,
                        "image_key": bool(os.getenv("POLLINATIONS_API_KEY")),
                        "runway_key": bool(os.getenv("RUNWAYML_API_SECRET")),
                        "anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY"))})
        elif path == "/api/status":
            with JOB.lock:
                ready = bool(JOB.dir and (JOB.dir / "output.mp4").exists())
                self._json({"status": JOB.status, "log": JOB.log[-60:], "total": JOB.total,
                            "done": JOB.done, "pct": JOB.pct, "phase": JOB.phase,
                            "elapsed": JOB.elapsed(), "video": JOB.status == "done" and ready})
        elif path == "/output.mp4":
            self._video()
        elif path.startswith("/api/"):
            self.send_error(404)
        else:
            self._static(path)

    def _video(self) -> None:
        file = JOB.dir / "output.mp4" if JOB.dir else None
        if not file or not file.exists():
            return self.send_error(404)
        size = file.stat().st_size
        start, end, code = 0, size - 1, 200
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else end
            else:
                start = max(0, size - int(match.group(2)))
            end, code = min(end, size - 1), 206
        try:
            self.send_response(code)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with file.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError):
            pass

    def do_POST(self) -> None:
        if not self._host_ok() or self.headers.get("X-Requested-With") != "faceless-ui":
            return self._json({"error": "Forbidden"}, 403)
        path = urllib.parse.urlparse(self.path).path
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if path == "/api/start":
                start_job(data)
                return self._json({"ok": True})
            if path == "/api/cancel":
                cancel_job()
                return self._json({"ok": True})
            if path == "/api/fetch":
                return self._json({"text": fetch_link(str(data.get("url", "")))})
            if path == "/api/script":
                from .script_writer import write_script
                topic = str(data.get("topic", "")).strip()
                if not topic:
                    raise ValueError("Type a topic first.")
                return self._json({"text": write_script(topic, seconds=max(10, int(data.get("seconds", 60))))})
            if path == "/api/plan":
                return self._json(plan_scenes(data))
            if path == "/api/preview":
                return self._json(preview_scenes(data))
            if path == "/api/demo":
                return self._json(demo_plan())
            self._json({"error": "Not found"}, 404)
        except Exception as exc:  # shown to the user in the page
            self._json({"error": str(exc)}, 400)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local web page for the video generator.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Video maker page: {url}  (press Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        cancel_job()


if __name__ == "__main__":
    main()
