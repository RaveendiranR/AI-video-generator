"""Motion-graphics renderer: spec validation, frames, planning, encoding and audio (offline)."""

import contextlib
import copy
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import ImageChops

from faceless_video_generator.media import require_binary
from faceless_video_generator.motion import (
    DEMO_SPEC,
    PlanError,
    SpecError,
    normalize_spec,
    plan_from_script,
    plan_from_script_ai,
    plan_from_topic,
    plan_script,
    script_fidelity,
    render_video,
)
from faceless_video_generator.motion import draw as D
from faceless_video_generator.motion.cli import main as cli_main
from faceless_video_generator.motion.render import (
    build_context,
    build_themes,
    render_frame,
    scene_durations,
)

FFMPEG = require_binary("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def probe(path: Path, entries: str) -> dict[str, str]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", entries, "-of", "default=nw=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


class SpecTests(unittest.TestCase):
    def test_demo_spec_is_valid_and_uppercased(self):
        spec = normalize_spec(DEMO_SPEC)
        self.assertEqual([s["type"] for s in spec["scenes"]], ["hook", "kinetic", "steps", "chart", "outro"])
        self.assertEqual(spec["scenes"][0]["accent"], "WILLPOWER.")
        self.assertEqual(spec["scenes"][3]["value"], "37x")  # units keep their case

    def test_no_caps_keeps_case(self):
        spec = normalize_spec(DEMO_SPEC, uppercase=False)
        self.assertEqual(spec["scenes"][0]["accent"], "willpower.")

    def test_errors_name_the_scene_and_field(self):
        cases = [
            ({"scenes": [{"type": "nope"}]}, "scene 1"),
            ({"scenes": [{"type": "kinetic"}]}, "'big' is required"),
            ({"scenes": [{"type": "hook", "accent": "x", "duration": 99}]}, "duration"),
            ({"scenes": [{"type": "steps", "nodes": ["only one"]}]}, "2 to 5"),
            ({"scenes": [{"type": "outro", "lines": []}]}, "at least one line"),
            ({"scenes": [{"type": "hook", "accent": "x", "theme": "neon"}]}, "theme"),
            ({"style": {"accent": "orange"}, "scenes": [{"type": "kinetic", "big": "x"}]}, "accent"),
            ({"scenes": []}, "non-empty"),
            ("not a spec", "JSON object"),
        ]
        for spec, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(SpecError) as ctx:
                    normalize_spec(spec)
                self.assertIn(message, str(ctx.exception))

    def test_list_shorthand_and_string_lines(self):
        spec = normalize_spec([{"type": "outro", "lines": "one line"}])
        self.assertEqual(spec["scenes"][0]["lines"], ["ONE LINE"])


class DrawTests(unittest.TestCase):
    def test_easing_is_bounded_and_hits_endpoints(self):
        for fn in (D.ease_out_cubic, D.ease_in_out, D.ease_out_back):
            self.assertAlmostEqual(fn(0), 0, places=6)
            self.assertAlmostEqual(fn(1), 1, places=6)
            self.assertAlmostEqual(fn(-5), fn(0), places=6)
        self.assertGreater(D.ease_out_back(0.7), 1.0)  # overshoots, which gives the "pop"

    def test_seg(self):
        self.assertEqual(D.seg(0.5, 1, 2), 0.0)
        self.assertEqual(D.seg(2, 1, 2), 0.5)
        self.assertEqual(D.seg(9, 1, 2), 1.0)
        self.assertEqual(D.seg(0.9, 1, 0), 0.0)

    def test_colours(self):
        self.assertEqual(D.hex_rgb("#fff"), (255, 255, 255))
        self.assertEqual(D.hex_rgb("E8630A"), (232, 99, 10))
        with self.assertRaises(ValueError):
            D.hex_rgb("#12")
        with self.assertRaises(ValueError):
            D.hex_rgb("#zzzzzz")
        self.assertEqual(D.mix((0, 0, 0), (100, 200, 50), 0.5), (50, 100, 25))

    def test_wrap_and_fit(self):
        font = D.resolve_font_path("bold")
        lines = D.wrap_text("one two three four five six seven", font, 60, 300)
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines), "one two three four five six seven")
        size = D.fit_size("A VERY LONG HEADLINE INDEED", font, 200, 400)
        self.assertLess(size, 200)
        self.assertLessEqual(D.text_width("A VERY LONG HEADLINE INDEED", font, size), 400)

    def test_missing_font_override_is_a_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            D.resolve_font_path("bold", "/no/such/font.ttf")


class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = normalize_spec(DEMO_SPEC)
        cls.ctx = build_context(270, 480)
        cls.themes = build_themes(cls.spec)

    def test_every_scene_animates_in_and_fills_the_frame(self):
        for scene in self.spec["scenes"]:
            with self.subTest(scene=scene["type"]):
                start = render_frame(scene, 0.0, self.ctx, self.themes)
                end = render_frame(scene, scene["duration"] * 0.95, self.ctx, self.themes)
                self.assertEqual(end.size, (270, 480))
                self.assertIsNotNone(ImageChops.difference(start, end).getbbox(), "nothing animated")
                self.assertGreater(len(set(end.get_flattened_data() if hasattr(end, "get_flattened_data") else end.getdata())), 3)

    def test_first_frame_has_no_text_flash(self):
        hook = self.spec["scenes"][0]
        frame = render_frame(hook, 0.0, self.ctx, self.themes)
        self.assertEqual(frame.getcolors(maxcolors=10)[0][0], 270 * 480 - sum(c for c, _ in frame.getcolors(maxcolors=10)[1:]))

    def test_chart_curve_grows_over_time(self):
        chart = self.spec["scenes"][3]
        early = render_frame(chart, 0.7, self.ctx, self.themes)
        later = render_frame(chart, 2.0, self.ctx, self.themes)
        self.assertIsNotNone(ImageChops.difference(early, later).getbbox())

    def test_all_curves_are_monotonic_from_zero_to_one(self):
        from faceless_video_generator.motion.scenes import curve_value

        for kind in ("exp", "linear", "log", "s"):
            values = [curve_value(kind, i / 50) for i in range(51)]
            self.assertAlmostEqual(values[0], 0, places=6)
            self.assertAlmostEqual(values[-1], 1, places=6)
            self.assertEqual(values, sorted(values))

    def test_long_text_and_five_nodes_do_not_crash(self):
        spec = normalize_spec(
            {
                "scenes": [
                    {"type": "hook", "lines": ["A VERY VERY LONG LINE OF TEXT THAT MUST SHRINK"], "accent": "WILLPOWER-AND-MORE."},
                    {"type": "steps", "nodes": [{"label": f"NODE {i}", "sub": "SUB"} for i in range(5)]},
                    {"type": "chart", "title": "x " * 50, "value": "1,000x", "show_curve": False},
                ]
            }
        )
        for scene in spec["scenes"]:
            render_frame(scene, scene["duration"], self.ctx, build_themes(spec))


class PlannerTests(unittest.TestCase):
    SCRIPT = (
        "Discipline starts with a morning that never drags. The alarm sounds, they rise, no snooze. "
        "Success rates jump 37% when goals are written down. Focus. "
        "They map the day in minutes, not hours, with a simple list and a clear target for each task. "
        "This is how disciplined people stay ahead, every single day."
    )

    def test_script_plan_shape(self):
        spec = plan_from_script(self.SCRIPT)
        types = [s["type"] for s in spec["scenes"]]
        self.assertEqual(types[0], "hook")
        self.assertEqual(types[-1], "outro")
        self.assertIn("chart", types)  # the 37% sentence becomes a stat scene
        stat = next(s for s in spec["scenes"] if s["type"] == "chart")
        self.assertEqual(stat["value"], "37%")
        self.assertFalse(stat["show_curve"])
        self.assertIn("kinetic", types)  # the one-word sentence
        for scene in spec["scenes"]:
            self.assertTrue(scene["narration"])

    def test_list_sentence_becomes_a_steps_diagram(self):
        spec = plan_from_script(
            "Start now. They protect the body that fuels the mind: exercise, proper meals, enough sleep, no shortcuts. Done."
        )
        steps = next(s for s in spec["scenes"] if s["type"] == "steps")
        self.assertEqual([n["label"] for n in steps["nodes"]], ["EXERCISE", "PROPER MEALS", "ENOUGH SLEEP", "NO SHORTCUTS"])
        self.assertFalse(steps["loop"])
        self.assertEqual(steps["nodes"][0]["title"], "THEY PROTECT THE BODY THAT FUELS THE MIND")

    def test_long_list_headline_is_cut_on_a_word_boundary(self):
        spec = plan_from_script(
            "Go. Everyone who wants lasting change should protect the body that fuels the mind: sleep, food, water. End."
        )
        title = next(s for s in spec["scenes"] if s["type"] == "steps")["nodes"][0]["title"]
        self.assertLessEqual(len(title), 48)
        self.assertTrue("EVERYONE WHO WANTS LASTING CHANGE SHOULD PROTECT THE BODY THAT FUELS THE MIND".startswith(title + " "))

    def test_scenes_break_at_natural_pauses_and_accents_have_no_dangling_punctuation(self):
        spec = plan_from_script(
            "Begin here. Every hour, a quick check: what's done, what's next, adjustments made on the fly. End here."
        )
        cards = [s for s in spec["scenes"] if s["type"] == "hook"][1:]
        self.assertEqual(cards[0]["accent"], "CHECK")  # "Every hour, a quick check:" is its own scene
        for scene in spec["scenes"]:
            self.assertFalse(scene.get("accent", "").endswith((",", ":", ";")))

    def test_script_plan_handles_one_and_two_sentences_and_empty(self):
        self.assertEqual([s["type"] for s in plan_from_script("Just one.")["scenes"]], ["hook"])
        self.assertEqual([s["type"] for s in plan_from_script("First. Second.")["scenes"]], ["hook", "outro"])
        with self.assertRaises(PlanError):
            plan_from_script("   ")

    def test_script_plan_caps_scene_count(self):
        text = " ".join(f"Sentence number {i} says something useful today." for i in range(150))
        self.assertLessEqual(len(plan_from_script(text, max_scenes=20)["scenes"]), 20)

    def test_topic_plan_parses_fenced_json(self):
        reply = "```json\n" + json.dumps(DEMO_SPEC) + "\n```"
        spec = plan_from_topic("habits", lambda prompt: reply, accent="#3366FF")
        self.assertEqual(len(spec["scenes"]), 5)
        self.assertEqual(spec["style"]["accent"], "#3366FF")

    def test_topic_plan_retries_with_feedback(self):
        prompts = []

        def completer(prompt):
            prompts.append(prompt)
            return "sorry, no json" if len(prompts) == 1 else json.dumps(DEMO_SPEC)

        spec = plan_from_topic("habits", completer)
        self.assertEqual(len(prompts), 2)
        self.assertIn("rejected", prompts[1])
        self.assertEqual(len(spec["scenes"]), 5)

    def test_topic_plan_gives_up_clearly(self):
        bad = copy.deepcopy(DEMO_SPEC)
        bad["scenes"][0]["type"] = "explosion"
        with self.assertRaises(PlanError) as ctx:
            plan_from_topic("habits", lambda prompt: json.dumps(bad), attempts=2)
        self.assertIn("2 attempts", str(ctx.exception))


@unittest.skipUnless(FFPROBE, "ffprobe is required")
class AiScriptPlannerTests(unittest.TestCase):
    SCRIPT = (
        "Your habits aren't about willpower. They're loops. A cue triggers a routine, and the routine earns a reward. "
        "Improve by one percent every day and you end up 37x better in a year. So build the loop, change the habit."
    )
    GOOD = {"scenes": [
        {"type": "hook", "tag": "habit science", "lines": ["Your habits", "aren't about"], "accent": "willpower.",
         "narration": "Your habits aren't about willpower."},
        {"type": "kinetic", "small": "They're", "big": "Loops.", "narration": "They're loops."},
        {"type": "steps", "tag": "the loop", "loop": True, "nodes": [{"label": "Cue"}, {"label": "Routine"}, {"label": "Reward"}],
         "narration": "A cue triggers a routine, and the routine earns a reward."},
        {"type": "chart", "tag": "proof", "title": "1% a day is 37x a year", "curve": "exp", "value": "37x",
         "x_labels": ["Day 1", "Day 365"],
         "narration": "Improve by one percent every day and you end up 37x better in a year."},
        {"type": "outro", "lines": ["Build the loop.", "Change the habit."], "narration": "So build the loop, change the habit."},
    ]}

    def test_model_choices_are_used_and_words_are_preserved(self):
        prompts = []

        def completer(prompt):
            prompts.append(prompt)
            return "Here you go:\n```json\n" + json.dumps(self.GOOD) + "\n```"

        spec = plan_from_script_ai(self.SCRIPT, completer, tag="Habits")
        self.assertEqual([s["type"] for s in spec["scenes"]], ["hook", "kinetic", "steps", "chart", "outro"])
        self.assertGreater(script_fidelity(self.SCRIPT, spec), 0.99)
        self.assertEqual(spec["scenes"][3]["value"], "37x")
        self.assertEqual(spec["scenes"][4]["tag"], "HABITS")  # scenes the model left unlabelled get the page label
        self.assertIn(self.SCRIPT, prompts[0])
        self.assertIn("EXACTLY", prompts[0])
        self.assertIn("first scene must be a \"hook\"", prompts[0])

    def test_overlong_labels_are_trimmed_not_rejected(self):
        data = json.loads(json.dumps(self.GOOD))
        data["scenes"][2]["nodes"][2]["label"] = "Reward that is extremely long"
        calls = []
        spec = plan_from_script_ai(self.SCRIPT, lambda p: calls.append(p) or json.dumps(data))
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(len(spec["scenes"][2]["nodes"][2]["label"]), 14)

    def test_rewritten_narration_is_rejected_then_falls_back_for_that_part(self):
        drifted = json.loads(json.dumps(self.GOOD))
        drifted["scenes"][1]["narration"] = "A totally different sentence appears here."
        drifted["scenes"] = drifted["scenes"][:2]
        warnings, calls = [], []
        spec = plan_from_script_ai(self.SCRIPT, lambda p: calls.append(p) or json.dumps(drifted), on_warning=warnings.append)
        self.assertEqual(len(calls), 2)  # one retry with feedback
        self.assertIn("rejected", calls[1])
        self.assertEqual(len(warnings), 1)
        self.assertGreater(script_fidelity(self.SCRIPT, spec), 0.99)  # the offline plan still speaks every word

    def test_a_retry_can_recover(self):
        replies = iter(["not json at all", json.dumps(self.GOOD)])
        spec = plan_from_script_ai(self.SCRIPT, lambda p: next(replies))
        self.assertEqual(len(spec["scenes"]), 5)

    def test_long_scripts_are_planned_in_parts_with_matching_positions(self):
        sentences = [f"Point number {n} explains one clear idea for you today." for n in range(1, 13)]
        script = " ".join(sentences)
        seen = []

        def completer(prompt):
            text = prompt.split("NARRATION:\n", 1)[1].strip()
            seen.append(prompt)
            scenes = [{"type": "hook", "lines": ["Point"], "accent": "idea", "narration": part} for part in text.split(". ") if part]
            scenes = [dict(sc, narration=sc["narration"].rstrip(".") + ".") for sc in scenes]
            if "ENDING" in prompt:
                scenes[-1] = {"type": "outro", "lines": ["Done"], "narration": scenes[-1]["narration"]}
            return json.dumps({"scenes": scenes})

        spec = plan_from_script_ai(script, completer, batch_words=40)
        self.assertGreater(len(seen), 2)
        self.assertIn("OPENING", seen[0])
        self.assertIn("MIDDLE", seen[1])
        self.assertIn("ENDING", seen[-1])
        self.assertGreater(script_fidelity(script, spec), 0.99)
        self.assertEqual(spec["scenes"][-1]["type"], "outro")

    def test_unreachable_model_raises_and_plan_script_falls_back(self):
        def down(prompt):
            raise RuntimeError("no internet")

        with self.assertRaises(PlanError):
            plan_from_script_ai(self.SCRIPT, down)
        warnings = []
        spec = plan_script(self.SCRIPT, down, on_warning=warnings.append)
        self.assertEqual(spec["scenes"][0]["type"], "hook")
        self.assertIn("offline planner", warnings[0])
        self.assertEqual(plan_script(self.SCRIPT)["scenes"], plan_from_script(self.SCRIPT)["scenes"])

    def test_no_caps_is_honoured_when_planning_from_a_script(self):
        spec = plan_from_script("Your habits aren't about Willpower. Small steps win.", uppercase=False)
        self.assertEqual(spec["scenes"][0]["accent"], "Willpower.")
        self.assertFalse(spec["style"]["uppercase"])

    def test_fidelity_ignores_case_and_punctuation(self):
        spec = {"scenes": [{"narration": "HELLO, world"}, {"narration": "again!"}]}
        self.assertEqual(script_fidelity("hello world. Again", spec), 1.0)
        self.assertLess(script_fidelity("hello world again", {"scenes": [{"narration": "goodbye"}]}), 0.5)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        raw = copy.deepcopy(DEMO_SPEC)
        for scene in raw["scenes"]:
            scene["duration"] = 1.5
        self.spec = normalize_spec(raw)

    def render(self, **kwargs):
        return render_video(
            self.spec, self.tmp / "out.mp4", ffmpeg=FFMPEG, width=270, height=480, fps=10,
            preset="ultrafast", crf=30, work_dir=self.tmp / "work", **kwargs,
        )

    def test_silent_video_has_expected_size_length_and_no_audio(self):
        out = self.render()
        info = probe(out, "format=duration:stream=codec_type,width,height")
        self.assertEqual((info["width"], info["height"]), ("270", "480"))
        self.assertAlmostEqual(float(info["duration"]), 7.5, delta=0.15)
        self.assertNotIn("audio", info.values())
        self.assertFalse((self.tmp / "out.tmp.mp4").exists())

    def test_odd_dimensions_are_rejected(self):
        with self.assertRaises(Exception) as ctx:
            render_video(self.spec, self.tmp / "x.mp4", ffmpeg=FFMPEG, width=271, height=480)
        self.assertIn("even", str(ctx.exception))

    def test_narration_stretches_scenes_and_adds_audio(self):
        calls = []

        def fake_synth(text, output):
            calls.append(text)
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=2.5", "-ar", "44100", str(output)],
                check=True,
            )

        out = self.render(synth=fake_synth)
        self.assertEqual(len(calls), 5)
        info = probe(out, "format=duration:stream=codec_type")
        # 5 scenes x (2.5s speech + 0.4s tail) = 14.5s, longer than the 7.5s in the spec.
        self.assertAlmostEqual(float(info["duration"]), 14.5, delta=0.3)
        self.assertIn("audio", info.values())
        # Re-rendering reuses the cached narration instead of synthesising again.
        (self.tmp / "out.mp4").unlink()
        self.render(synth=fake_synth)
        self.assertEqual(len(calls), 5)

    def test_scenes_without_narration_stay_silent_but_keep_sync(self):
        self.spec["scenes"][1]["narration"] = ""

        def fake_synth(text, output):
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-ar", "44100", str(output)],
                check=True,
            )

        out = self.render(synth=fake_synth)
        expected = sum(scene_durations(self.spec, [2, None, 2, 2, 2]))
        self.assertAlmostEqual(float(probe(out, "format=duration")["duration"]), expected, delta=0.3)

    def test_music_only_adds_an_audio_track(self):
        bed = self.tmp / "bed.wav"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=200:duration=3", str(bed)], check=True)
        out = self.render(music=bed)
        self.assertIn("audio", probe(out, "stream=codec_type").values())


@unittest.skipUnless(FFPROBE, "ffprobe is required")
class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli_main(list(args))
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_lists_scenes(self):
        code, out, _ = self.run_cli("--demo", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("5 scenes", out)
        self.assertIn("steps", out)

    def test_requires_a_source(self):
        code, _, err = self.run_cli("--dry-run")
        self.assertNotEqual(code, 0)
        self.assertIn("choose a source", err)

    def test_preview_writes_one_png_per_scene(self):
        code, out, _ = self.run_cli("--demo", "--preview", str(self.tmp / "p"), "--width", "270", "--height", "480")
        self.assertEqual(code, 0)
        self.assertEqual(len(list((self.tmp / "p").glob("*.png"))), 5)

    def test_save_spec_round_trips(self):
        spec_path = self.tmp / "spec.json"
        self.run_cli("--demo", "--dry-run", "--save-spec", str(spec_path))
        code, out, _ = self.run_cli("--spec", str(spec_path), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("5 scenes", out)

    def test_script_source_and_render_and_overwrite_protection(self):
        script = self.tmp / "s.txt"
        script.write_text("Habits shape everything. They compound daily. Start small today.", encoding="utf-8")
        out_path = self.tmp / "v.mp4"
        args = ["--script", str(script), "-o", str(out_path), "--work-dir", str(self.tmp / "w"),
                "--width", "270", "--height", "480", "--fps", "10", "--preset", "ultrafast", "--crf", "32"]
        code, out, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        self.assertTrue(out_path.exists())
        code, _, err = self.run_cli(*args)
        self.assertNotEqual(code, 0)
        self.assertIn("--force", err)

    def test_bad_spec_reports_error_without_traceback(self):
        bad = self.tmp / "bad.json"
        bad.write_text('{"scenes": [{"type": "kinetic"}]}', encoding="utf-8")
        code, _, err = self.run_cli("--spec", str(bad), "--dry-run")
        self.assertNotEqual(code, 0)
        self.assertIn("'big' is required", err)

    def test_ai_plan_needs_a_script_and_falls_back_offline(self):
        code, _, err = self.run_cli("--demo", "--ai-plan", "--dry-run")
        self.assertNotEqual(code, 0)
        self.assertIn("--ai-plan needs --script", err)

        from unittest import mock

        script = self.tmp / "s.txt"
        script.write_text("Habits shape everything. They compound daily. Start small today.", encoding="utf-8")

        def down(prompt, *a, **kw):
            raise RuntimeError("no internet")

        with mock.patch("faceless_video_generator.script_writer._complete_with_retry", down):
            code, out, _ = self.run_cli("--script", str(script), "--ai-plan", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("3 scenes", out)

    def test_no_caps_script_plan_keeps_your_case(self):
        script = self.tmp / "s.txt"
        script.write_text("Habits shape Everything. They compound daily. Start small today.", encoding="utf-8")
        saved = self.tmp / "spec.json"
        code, _, err = self.run_cli("--script", str(script), "--no-caps", "--dry-run", "--save-spec", str(saved))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["scenes"][0]["accent"], "Everything.")


if __name__ == "__main__":
    unittest.main()
