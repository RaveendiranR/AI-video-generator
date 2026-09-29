"""Scene spec: themes, validation and normalisation.

A spec is plain JSON so it can be written by hand, produced by an LLM, or generated
from a narration script::

    {"style": {"accent": "#E8630A"},
     "scenes": [{"type": "hook", "tag": "HABIT SCIENCE", "lines": ["YOUR HABITS"],
                 "accent": "WILLPOWER.", "duration": 3.5}]}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .draw import Color, hex_rgb, mix

SCENE_TYPES = ("hook", "kinetic", "steps", "chart", "outro")
THEME_NAMES = ("light", "dark", "accent")
ICONS = ("spark", "cycle", "star", "check", "bolt", "dot")
CURVES = ("exp", "linear", "log", "s")

DEFAULT_ACCENT = "#E8630A"
DEFAULT_DURATION = 3.5
MIN_DURATION, MAX_DURATION = 1.0, 30.0
DEFAULT_THEME = {"hook": "light", "kinetic": "dark", "steps": "light", "chart": "dark", "outro": "accent"}


class SpecError(ValueError):
    """Raised when a scene spec is invalid; the message says which scene and field."""


@dataclass(frozen=True)
class Theme:
    name: str
    bg: Color
    fg: Color  # main text
    second: Color  # secondary text colour (outro line 2)
    muted: Color
    accent: Color  # highlight colour for text, lines and shapes
    pill_bg: Color
    pill_fg: Color
    panel: Color
    node_fill: Color


def make_theme(name: str, accent_hex: str = DEFAULT_ACCENT) -> Theme:
    accent = hex_rgb(accent_hex)
    ink = (25, 23, 21)
    cream = (250, 244, 237)
    if name == "light":
        return Theme(
            name, cream, ink, ink, (120, 113, 104), mix(accent, ink, 0.06),
            mix(accent, cream, 0.82), mix(accent, ink, 0.12), (255, 255, 255), (255, 255, 255),
        )
    if name == "dark":
        return Theme(
            name, ink, (255, 255, 255), (255, 255, 255), (158, 152, 143), mix(accent, (255, 255, 255), 0.04),
            mix(accent, ink, 0.78), mix(accent, (255, 255, 255), 0.04), (33, 31, 29), (255, 255, 255),
        )
    if name == "accent":
        bg = mix(accent, (0, 0, 0), 0.05)
        return Theme(
            name, bg, (255, 255, 255), ink, (255, 255, 255), (255, 255, 255),
            (255, 255, 255), ink, mix(bg, ink, 0.2), (255, 255, 255),
        )
    raise SpecError(f"Unknown theme {name!r}; choose one of {', '.join(THEME_NAMES)}.")


def _text(scene: dict, key: str, where: str, *, required: bool = False, limit: int = 120) -> str:
    value = scene.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise SpecError(f"{where}: '{key}' must be text.")
    value = " ".join(str(value).split())
    if required and not value:
        raise SpecError(f"{where}: '{key}' is required.")
    if len(value) > limit:
        raise SpecError(f"{where}: '{key}' is too long ({len(value)} > {limit} characters).")
    return value


def _lines(scene: dict, key: str, where: str, *, required: bool = False, max_lines: int = 6) -> list[str]:
    raw = scene.get(key, [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(item, (str, int, float)) for item in raw):
        raise SpecError(f"{where}: '{key}' must be a list of text lines.")
    lines = [" ".join(str(item).split()) for item in raw if str(item).strip()]
    if required and not lines:
        raise SpecError(f"{where}: '{key}' needs at least one line.")
    if len(lines) > max_lines:
        raise SpecError(f"{where}: '{key}' has {len(lines)} lines; the maximum is {max_lines}.")
    return lines


def normalize_scene(scene: Any, index: int, *, uppercase: bool = True) -> dict[str, Any]:
    where = f"scene {index + 1}"
    if not isinstance(scene, dict):
        raise SpecError(f"{where}: must be an object.")
    kind = str(scene.get("type", "")).strip().lower()
    if kind not in SCENE_TYPES:
        raise SpecError(f"{where}: unknown type {scene.get('type')!r}; choose one of {', '.join(SCENE_TYPES)}.")
    where = f"scene {index + 1} ({kind})"

    theme = str(scene.get("theme") or DEFAULT_THEME[kind]).lower()
    if theme not in THEME_NAMES:
        raise SpecError(f"{where}: unknown theme {theme!r}; choose one of {', '.join(THEME_NAMES)}.")

    try:
        duration = float(scene.get("duration", DEFAULT_DURATION))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{where}: 'duration' must be a number of seconds.") from exc
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise SpecError(f"{where}: 'duration' must be between {MIN_DURATION:g} and {MAX_DURATION:g} seconds.")

    up = (lambda s: s.upper()) if uppercase else (lambda s: s)
    out: dict[str, Any] = {
        "type": kind,
        "theme": theme,
        "duration": duration,
        "tag": up(_text(scene, "tag", where, limit=40)),
        "narration": _text(scene, "narration", where, limit=1200),
    }

    if kind == "hook":
        out["lines"] = [up(x) for x in _lines(scene, "lines", where)]
        out["accent"] = up(_text(scene, "accent", where, limit=40))
        if not out["lines"] and not out["accent"]:
            raise SpecError(f"{where}: give 'lines' and/or 'accent' text.")
    elif kind == "kinetic":
        out["small"] = up(_text(scene, "small", where, limit=40))
        out["big"] = up(_text(scene, "big", where, required=True, limit=24))
        out["spinner"] = bool(scene.get("spinner", True))
    elif kind == "steps":
        raw_nodes = scene.get("nodes")
        if not isinstance(raw_nodes, list) or not 2 <= len(raw_nodes) <= 5:
            raise SpecError(f"{where}: 'nodes' must be a list of 2 to 5 items.")
        nodes = []
        for n, node in enumerate(raw_nodes):
            if isinstance(node, str):
                node = {"label": node}
            if not isinstance(node, dict):
                raise SpecError(f"{where}: node {n + 1} must be an object or text.")
            icon = str(node.get("icon", ICONS[n % len(ICONS)])).lower()
            if icon not in ICONS:
                raise SpecError(f"{where}: node {n + 1} icon {icon!r} is unknown; choose one of {', '.join(ICONS)}.")
            label = up(_text(node, "label", f"{where}, node {n + 1}", required=True, limit=14))
            nodes.append(
                {
                    "label": label,
                    "sub": up(_text(node, "sub", f"{where}, node {n + 1}", limit=18)),
                    "icon": icon,
                    "title": up(_text(node, "title", f"{where}, node {n + 1}", limit=48)) or f"STEP {n + 1}: {label}",
                }
            )
        out["nodes"] = nodes
        out["loop"] = bool(scene.get("loop", True))
    elif kind == "chart":
        out["title"] = up(_text(scene, "title", where, limit=110))
        out["curve"] = str(scene.get("curve", "exp")).lower()
        if out["curve"] not in CURVES:
            raise SpecError(f"{where}: unknown curve {out['curve']!r}; choose one of {', '.join(CURVES)}.")
        out["show_curve"] = bool(scene.get("show_curve", True))
        labels = _lines(scene, "x_labels", where, max_lines=3)
        out["x_labels"] = [up(x[:12]) for x in labels]
        out["value"] = _text(scene, "value", where, limit=10)  # keep case: "37x"
        out["caption"] = up(_text(scene, "caption", where, limit=40))
        if not (out["title"] or out["value"]):
            raise SpecError(f"{where}: give a 'title' and/or a 'value'.")
    elif kind == "outro":
        out["lines"] = [up(x) for x in _lines(scene, "lines", where, required=True, max_lines=4)]
        out["spinner"] = bool(scene.get("spinner", True))
    return out


def normalize_spec(spec: Any, *, uppercase: bool = True) -> dict[str, Any]:
    """Validate a spec and return a normalised copy with defaults filled in."""
    if isinstance(spec, list):
        spec = {"scenes": spec}
    if not isinstance(spec, dict):
        raise SpecError("The spec must be a JSON object with a 'scenes' list.")
    raw_scenes = spec.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise SpecError("The spec needs a non-empty 'scenes' list.")
    if len(raw_scenes) > 60:
        raise SpecError("A spec can contain at most 60 scenes.")
    style = spec.get("style") or {}
    if not isinstance(style, dict):
        raise SpecError("'style' must be an object, for example {\"accent\": \"#E8630A\"}.")
    accent = str(style.get("accent", DEFAULT_ACCENT))
    try:
        hex_rgb(accent)
    except ValueError as exc:
        raise SpecError(f"style.accent: {exc}") from exc
    return {
        "style": {"accent": accent, "uppercase": bool(style.get("uppercase", uppercase))},
        "scenes": [
            normalize_scene(scene, i, uppercase=bool(style.get("uppercase", uppercase)))
            for i, scene in enumerate(raw_scenes)
        ],
    }


DEMO_SPEC: dict[str, Any] = {
    "style": {"accent": DEFAULT_ACCENT},
    "scenes": [
        {
            "type": "hook", "tag": "Habit Science", "duration": 3.6,
            "lines": ["Your habits", "aren't about"], "accent": "willpower.",
            "narration": "Your habits aren't about willpower.",
        },
        {
            "type": "kinetic", "small": "They're", "big": "Loops.", "duration": 2.6,
            "narration": "They're loops.",
        },
        {
            "type": "steps", "tag": "The Habit Loop", "duration": 6.0, "loop": True,
            "nodes": [
                {"label": "Cue", "sub": "Trigger", "icon": "spark", "title": "Step 1: The Trigger"},
                {"label": "Routine", "sub": "Behavior", "icon": "cycle", "title": "Step 2: The Action"},
                {"label": "Reward", "sub": "Dopamine hit", "icon": "star", "title": "Step 3: The Payoff"},
            ],
            "narration": "A cue triggers a routine, and the routine earns a reward.",
        },
        {
            "type": "chart", "tag": "Mathematical Proof", "duration": 4.4, "curve": "exp",
            "title": "1% better every day compounds to 37x in a year.",
            "x_labels": ["Day 1", "Day 180", "Day 365"], "value": "37x", "caption": "Better after 365 days",
            "narration": "One percent better every day compounds to thirty-seven times in a year.",
        },
        {
            "type": "outro", "tag": "The Formula", "duration": 3.4,
            "lines": ["Build the loop.", "Change the habit."],
            "narration": "Build the loop. Change the habit.",
        },
    ],
}
