"""Turn a topic (online model) or a plain narration script (offline heuristics) into a scene spec."""

from __future__ import annotations

import json
import logging
import math
import re
import textwrap
from difflib import SequenceMatcher
from typing import Any, Callable

from ..pipeline import split_sentences
from ..script_writer import clean_narration
from .spec import DEFAULT_ACCENT, SpecError, normalize_spec

LOGGER = logging.getLogger("faceless_video_generator")

Completer = Callable[[str], str]

_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(%|x|X|k|K|M|B|percent)?(?![\w])")
WORDS_PER_SECOND = 2.6


class PlanError(RuntimeError):
    """Raised when a scene plan cannot be produced."""


def _duration(text: str, minimum: float = 2.6, maximum: float = 8.0) -> float:
    return round(min(maximum, max(minimum, len(text.split()) / WORDS_PER_SECOND + 1.0)), 2)


_CLAUSE_BREAK = re.compile(r"(?<=[,;:\u2014])\s+")
_LIST_ICONS = ("check", "spark", "star", "bolt", "cycle")


def _split_long(sentence: str, max_words: int = 12) -> list[str]:
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    parts = math.ceil(len(words) / max_words)
    size = math.ceil(len(words) / parts)
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def _wrap(text: str, width: int = 16) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False) or [text]


def _tidy(text: str) -> str:
    """Drop dangling clause punctuation so an accent word never ends in a colon."""
    return text.rstrip(",;:\u2014- ")


def _clause_chunks(sentence: str, min_words: int = 5, max_words: int = 12) -> list[str]:
    """Split at commas/colons into scene-sized chunks so lines break at natural pauses."""
    chunks: list[str] = []
    current: list[str] = []
    for clause in _CLAUSE_BREAK.split(sentence):
        current.append(clause)
        if sum(len(c.split()) for c in current) >= min_words:
            chunks.append(" ".join(current))
            current = []
    if current:
        tail = " ".join(current)
        if chunks and len((chunks[-1] + " " + tail).split()) <= max_words + 2:
            chunks[-1] = f"{chunks[-1]} {tail}"
        else:
            chunks.append(tail)
    return [piece for chunk in chunks for piece in _split_long(chunk, max_words)]


def _fit_words(text: str, limit: int) -> str:
    """Longest run of leading whole words that fits in ``limit`` characters."""
    out = ""
    for word in text.split():
        trial = f"{out} {word}".strip()
        if len(trial) > limit:
            break
        out = trial
    return out


def _parse_list(sentence: str) -> tuple[str, list[str]] | None:
    """Detect "Intro: a, b, c" or "a, b, c" lists of short items -> (headline, items)."""
    head, body = "", sentence
    if ":" in sentence:
        head, body = (part.strip() for part in sentence.split(":", 1))
    items = [re.sub(r"^(?:and|or)\s+", "", item.strip().rstrip(".!?"), flags=re.I) for item in body.split(",")]
    items = [item for item in items if item]
    if not 3 <= len(items) <= 5:
        return None
    if any(len(item) > 14 or len(item.split()) > 2 for item in items):
        return None
    return head, items


def _number_token(match: re.Match[str]) -> str:
    unit = match.group(2) or ""
    return match.group(1) + ("%" if unit == "percent" else unit)


def _headline(text: str, max_words: int = 12) -> list[str]:
    """First sentence of ``text``, cut to a card-sized headline (the full text stays as narration)."""
    first = (split_sentences(text) or [text])[0]
    return first.split()[:max_words]


def _content_scene(text: str, index: int, tag: str) -> dict[str, Any]:
    base = {"narration": text, "duration": _duration(text)}
    listed = _parse_list(text)
    if listed:
        head, items = listed
        title = _fit_words(head.upper(), 48) if head else ""
        nodes = [
            {"label": item, "icon": _LIST_ICONS[i % len(_LIST_ICONS)], **({"title": title} if title else {})}
            for i, item in enumerate(items)
        ]
        return {
            "type": "steps", "tag": tag, "loop": False, "nodes": nodes, "narration": text,
            "duration": round(max(4.0, 0.9 + 1.1 * len(items), _duration(text)), 2),
        }
    words = _headline(text)
    shown = " ".join(words)
    number = _NUMBER.search(shown)
    if number and len(words) >= 4 and len(shown) <= 110 and len(_number_token(number)) <= 10:
        return {"type": "chart", "tag": "BY THE NUMBERS", "title": shown, "show_curve": False,
                "value": _number_token(number), **base}
    if len(words) <= 4:
        return {"type": "kinetic", "small": _tidy(" ".join(words[:-1])), "big": words[-1][:24], **base}
    return {
        "type": "hook", "tag": tag, "lines": _wrap(_tidy(" ".join(words[:-1]))), "accent": _tidy(words[-1]),
        "theme": "dark" if index % 2 else "light", **base,
    }


def _sentence_chunks(text: str) -> list[str]:
    """Narration -> scene-sized chunks (lists stay whole, long sentences split at natural pauses)."""
    chunks: list[str] = []
    for sentence in split_sentences(clean_narration(text)):
        chunks.extend([sentence] if _parse_list(sentence) else _clause_chunks(sentence))
    return chunks


def _hook_scene(chunk: str, tag: str) -> dict[str, Any]:
    words = chunk.split()
    return {
        "type": "hook", "tag": tag, "theme": "light", "narration": chunk, "duration": _duration(chunk, 3.0),
        "lines": _wrap(_tidy(" ".join(words[:-1]))) if len(words) > 1 else [],
        "accent": _tidy(words[-1]),
    }


def _outro_scene(chunk: str) -> dict[str, Any]:
    return {"type": "outro", "tag": "REMEMBER", "narration": chunk, "duration": _duration(chunk, 3.0), "lines": [chunk]}


def _scenes_from_chunks(
    chunks: list[str], tag: str, *, opening: bool = True, closing: bool = True, max_scenes: int = 40
) -> list[dict[str, Any]]:
    """First chunk -> hook, last -> outro, the rest -> cards, lists, big words and stats."""
    body = list(chunks)
    scenes: list[dict[str, Any]] = []
    if opening and body:
        scenes.append(_hook_scene(body.pop(0), tag))
    last = body.pop() if closing and body else None
    budget = max(1, max_scenes - len(scenes) - (1 if last else 0))
    if len(body) > budget:
        group = math.ceil(len(body) / budget)
        body = [" ".join(body[i : i + group]) for i in range(0, len(body), group)]
    scenes.extend(_content_scene(chunk, i, tag) for i, chunk in enumerate(body))
    if last:
        scenes.append(_outro_scene(last))
    return scenes


def plan_from_script(
    text: str, *, tag: str = "KEY IDEA", accent: str = DEFAULT_ACCENT, max_scenes: int = 40, uppercase: bool = True
) -> dict[str, Any]:
    """Offline planner: first sentence -> hook, last -> outro, the rest -> cards, lists, big words, stats."""
    chunks = _sentence_chunks(text)
    if not chunks:
        raise PlanError("The script is empty.")
    scenes = _scenes_from_chunks(chunks, tag, max_scenes=max_scenes)
    try:
        return normalize_spec({"style": {"accent": accent, "uppercase": uppercase}, "scenes": scenes}, uppercase=uppercase)
    except SpecError as exc:  # pragma: no cover - defensive; the planner builds valid scenes
        raise PlanError(f"Could not plan scenes from the script: {exc}") from exc


_SHAPES = """\
Return ONLY one JSON object (no markdown, no commentary) shaped like:
{"scenes": [
 {"type":"hook","tag":"SHORT LABEL","lines":["FIRST LINE","SECOND LINE"],"accent":"LAST WORD.","narration":"...","duration":3.5},
 {"type":"kinetic","small":"THEY'RE","big":"LOOPS.","narration":"...","duration":2.6},
 {"type":"steps","tag":"THE LOOP","loop":true,"nodes":[
    {"label":"CUE","sub":"TRIGGER","icon":"spark","title":"STEP 1: THE TRIGGER"},
    {"label":"ROUTINE","sub":"BEHAVIOR","icon":"cycle","title":"STEP 2: THE ACTION"},
    {"label":"REWARD","sub":"PAYOFF","icon":"star","title":"STEP 3: THE PAYOFF"}],
  "narration":"...","duration":6},
 {"type":"chart","tag":"PROOF","title":"A CLAIM WITH A NUMBER","curve":"exp","x_labels":["DAY 1","DAY 180","DAY 365"],
  "value":"37x","caption":"BETTER AFTER 365 DAYS","narration":"...","duration":4.5},
 {"type":"outro","tag":"THE FORMULA","lines":["BUILD THE LOOP.","CHANGE THE HABIT."],"narration":"...","duration":3.5}
]}
"""

_TOPIC_RULES = """\
Rules: 6 to {max_scenes} scenes. First scene is a "hook", last is an "outro". Use "steps" (2-5 nodes, label max 12 chars,
icons from spark, cycle, star, check, bolt, dot) at most once and only when the topic has a real process. Use "chart"
(curve from exp, linear, log, s) only for a genuine number or trend, and set "show_curve": false for a plain big statistic.
Every text must be very short: hook lines under 16 characters each, "big" under 12 characters, chart titles under 90.
"narration" is the spoken sentence(s) for that scene, plain and natural. Each scene's duration in seconds should roughly
equal its narration word count divided by 2.6, plus 1. Total runtime about {seconds} seconds. Be accurate; do not invent statistics."""


_SCHEMA = _SHAPES + _TOPIC_RULES


def plan_from_topic(
    topic: str,
    completer: Completer,
    *,
    seconds: int = 45,
    accent: str = DEFAULT_ACCENT,
    attempts: int = 3,
) -> dict[str, Any]:
    """Ask a text model for a scene spec; validate it and feed errors back for a retry."""
    max_scenes = max(6, min(14, round(seconds / 4)))
    prompt = (
        f"You design short vertical explainer videos made of animated motion-graphics scenes.\n"
        f"Topic: {topic}\n\n" + _SCHEMA.replace("{max_scenes}", str(max_scenes)).replace("{seconds}", str(seconds))
    )
    feedback = ""
    last_error = "no response"
    for attempt in range(1, attempts + 1):
        raw = completer(prompt + feedback)
        try:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("the reply did not contain a JSON object")
            data = json.loads(raw[start : end + 1])
            if not isinstance(data, dict):
                raise ValueError("the JSON root must be an object")
            data.setdefault("style", {})["accent"] = accent
            for scene in data.get("scenes", []):
                if isinstance(scene, dict) and scene.get("type") == "kinetic" and len(str(scene.get("big", ""))) > 24:
                    scene["big"] = str(scene["big"])[:24]
            return normalize_spec(data)
        except (ValueError, SpecError) as exc:
            last_error = str(exc)
            LOGGER.warning("Scene plan attempt %d/%d was invalid: %s", attempt, attempts, last_error)
            feedback = f"\n\nYour previous answer was rejected: {last_error}. Fix that and return the corrected JSON only."
    raise PlanError(f"The model did not return a valid scene plan after {attempts} attempts ({last_error}).")


# --------------------------------------------------------------------------- AI reads your script
FIDELITY_MIN = 0.95  # how closely the scenes' narration must match the script (word for word)
_TEXT_LIMITS = {"tag": 40, "accent": 40, "small": 40, "title": 110, "caption": 40, "value": 10}
_NODE_LIMITS = {"label": 14, "sub": 18, "title": 48}
_MIN_SCENE_SECONDS = {"hook": 3.0, "kinetic": 2.6, "chart": 3.6, "outro": 3.0}

_SCRIPT_BRIEF = """\
You are a motion-graphics director turning a narration into an animated explainer video. A voice actor will speak the
narration word for word, so you decide only what is SHOWN on screen while each part is spoken.

Read the narration and understand what it means. Then split it into consecutive scenes, one idea per scene (roughly one scene
per {lo} to {hi} spoken words). Copy each scene's part of the narration EXACTLY into its "narration" field. Across all scenes
the narration fields must add up to the full text below, in order: never reword, summarise, translate, add, drop or reorder words.

Pick each scene's visual from what its words are about:
- "steps" (a diagram of 2 to 5 nodes): use it when the words describe a process, a cycle, a sequence of stages, a cause-and-effect
  chain, or a small set of parts or options. Each node label is the key noun (max 12 characters, for example CUE). Set "loop": true
  when the idea cycles back to its start, false for a one-way sequence. List nodes in the order the narration mentions them.
- "chart": use it when the words state a number, percentage, growth, decline or a comparison of quantities. "value" is the headline
  figure exactly as spoken (for example 37x or 90%). Set "curve" to "exp" for compounding or accelerating growth, "linear" for steady
  change, "log" for fast-then-flattening, "s" for adoption or tipping points. Set "show_curve": false for a plain statistic with no
  trend. Give 2 or 3 short "x_labels" taken from the text (for example DAY 1, DAY 365). Only use numbers that appear in the narration.
- "kinetic": one punchy word or short phrase that lands an emphasis ("big", max 12 characters). Use it sparingly.
- "hook": a statement or idea shown as big text: "lines" (short lines, max 16 characters each) then "accent" (the one word or phrase that
  matters most, shown in the highlight colour).
- "outro": the closing takeaway, only as the last scene of the whole video.
Keep every on-screen text short and taken from the narration. Vary the visuals so no two neighbouring scenes look the same.
{position}
"""

_POSITIONS = {
    "only": "This is the whole video: the first scene must be a \"hook\" and the last scene must be an \"outro\".",
    "first": "This is the OPENING of a longer video: the first scene must be a \"hook\". Do not use an \"outro\".",
    "middle": "This is the MIDDLE of a longer video: do not use an \"outro\". Start with whatever visual fits best.",
    "last": "This is the ENDING of a longer video: the last scene must be an \"outro\".",
}


def _words_of(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def script_fidelity(script: str, spec: dict[str, Any]) -> float:
    """0..1: how much of ``script`` the scenes' narration reproduces, ignoring case and punctuation."""
    want = _words_of(script)
    got = _words_of(" ".join(scene.get("narration", "") for scene in spec["scenes"]))
    if not want and not got:
        return 1.0
    return SequenceMatcher(None, want, got, autojunk=False).ratio()


def _clip(value: Any, limit: int) -> Any:
    if not isinstance(value, str):
        return value
    value = " ".join(value.split())
    return value if len(value) <= limit else (_fit_words(value, limit) or value[:limit]).rstrip(",;:\u2014- ")


def _sanitize_scene(scene: dict[str, Any]) -> dict[str, Any]:
    """Trim model output to the renderer's limits at word boundaries, so a long label never costs a retry."""
    for key, limit in _TEXT_LIMITS.items():
        if key in scene:
            scene[key] = _clip(scene[key], limit)
    if scene.get("type") == "kinetic" and "big" in scene:
        scene["big"] = _clip(scene["big"], 24)
    if isinstance(scene.get("nodes"), list):
        scene["nodes"] = scene["nodes"][:5]
        for node in scene["nodes"]:
            if isinstance(node, dict):
                for key, limit in _NODE_LIMITS.items():
                    if key in node:
                        node[key] = _clip(node[key], limit)
    return scene


def _finish_durations(spec: dict[str, Any]) -> None:
    """Timing from the narration length (the renderer stretches scenes to the real voice anyway)."""
    for scene in spec["scenes"]:
        base = _duration(scene["narration"], 2.6) if scene["narration"] else scene["duration"]
        if scene["type"] == "steps":
            base = max(base, 4.0 if scene["loop"] else 0.9 + 1.1 * len(scene["nodes"]))
        scene["duration"] = round(max(base, _MIN_SCENE_SECONDS.get(scene["type"], 0)), 2)


def _batches(sentences: list[str], batch_words: int) -> list[list[str]]:
    out: list[list[str]] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        n = len(sentence.split())
        if current and count + n > batch_words:
            out.append(current)
            current, count = [], 0
        current.append(sentence)
        count += n
    if current:
        out.append(current)
    return out


def _plan_batch(text: str, position: str, completer: Completer, attempts: int) -> list[dict[str, Any]]:
    prompt = (
        _SCRIPT_BRIEF.replace("{lo}", "8").replace("{hi}", "14").replace("{position}", _POSITIONS[position])
        + "\n"
        + _SHAPES
        + f"\n\nNARRATION:\n{text}\n"
    )
    feedback, last_error = "", "no response"
    for attempt in range(1, attempts + 1):
        raw = completer(prompt + feedback)  # a RuntimeError here means the model is unreachable
        try:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("the reply did not contain a JSON object")
            data = json.loads(raw[start : end + 1])
            if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
                raise ValueError("the JSON root must be an object with a 'scenes' list")
            data["scenes"] = [_sanitize_scene(sc) if isinstance(sc, dict) else sc for sc in data["scenes"]]
            if any(isinstance(sc, dict) and not str(sc.get("narration", "")).strip() for sc in data["scenes"]):
                raise ValueError("every scene needs its 'narration' text")
            spec = normalize_spec(data)
            fidelity = script_fidelity(text, spec)
            if fidelity < FIDELITY_MIN:
                raise ValueError(
                    f"the scenes' narration only matches {fidelity:.0%} of the narration; copy it word for word, "
                    "without dropping, adding or rewording anything"
                )
            return spec["scenes"]
        except (ValueError, SpecError) as exc:
            last_error = str(exc)
            LOGGER.warning("Scene plan attempt %d/%d was rejected: %s", attempt, attempts, last_error)
            feedback = f"\n\nYour previous answer was rejected: {last_error}. Fix that and return the corrected JSON only."
    raise PlanError(last_error)


def plan_from_script_ai(
    text: str,
    completer: Completer,
    *,
    tag: str = "KEY IDEA",
    accent: str = DEFAULT_ACCENT,
    uppercase: bool = True,
    attempts: int = 2,
    batch_words: int = 140,
    on_warning: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Let a text model read the script and choose a chart, diagram or typography scene for each part.

    The narration is checked against the script so the spoken words never drift. A part the model
    gets wrong twice falls back to the offline planner for that part only. If the model cannot be
    reached at all a ``PlanError`` is raised so the caller can plan everything offline.
    """
    warn = on_warning or (lambda message: LOGGER.warning("%s", message))
    sentences = split_sentences(clean_narration(text))
    if not sentences:
        raise PlanError("The script is empty.")
    batches = _batches(sentences, batch_words)
    scenes: list[dict[str, Any]] = []
    for n, batch in enumerate(batches, 1):
        position = "only" if len(batches) == 1 else "first" if n == 1 else "last" if n == len(batches) else "middle"
        chunk_text = " ".join(batch)
        LOGGER.info("Planning scenes with the text model (part %d of %d)", n, len(batches))
        try:
            part = _plan_batch(chunk_text, position, completer, attempts)
        except PlanError as exc:
            warn(f"Part {n} of {len(batches)}: the model's plan was not usable ({exc}); used the offline planner for it.")
            part = _scenes_from_chunks(
                _sentence_chunks(chunk_text), tag, opening=position in ("only", "first"), closing=position in ("only", "last")
            )
        except RuntimeError as exc:
            raise PlanError(f"The text model could not be reached: {exc}") from exc
        scenes.extend(part)
    if len(scenes) > 60:
        raise PlanError("The plan has more than 60 scenes; shorten the script or plan offline.")
    for scene in scenes:
        if scene.get("tag", "") == "" and scene["type"] in ("hook", "steps", "chart", "outro"):
            scene["tag"] = tag
    try:
        spec = normalize_spec({"style": {"accent": accent, "uppercase": uppercase}, "scenes": scenes}, uppercase=uppercase)
    except SpecError as exc:
        raise PlanError(f"Could not combine the scene plan: {exc}") from exc
    _finish_durations(spec)
    return spec


def plan_script(
    text: str,
    completer: Completer | None = None,
    *,
    tag: str = "KEY IDEA",
    accent: str = DEFAULT_ACCENT,
    uppercase: bool = True,
    on_warning: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Plan scenes from a script: with a ``completer`` the model reads it, otherwise (or if it fails) offline rules."""
    warn = on_warning or (lambda message: LOGGER.warning("%s", message))
    if completer is not None:
        try:
            return plan_from_script_ai(text, completer, tag=tag, accent=accent, uppercase=uppercase, on_warning=warn)
        except PlanError as exc:
            warn(f"{exc} Used the quick offline planner instead.")
    return plan_from_script(text, tag=tag, accent=accent, uppercase=uppercase)
