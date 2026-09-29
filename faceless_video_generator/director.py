from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ShotPlan:
    shot: str
    lens: str
    movement: str
    framing: str
    lighting: str
    focus: str
    transition: str
    energy: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


SHOT_LIBRARY = (
    ShotPlan("establishing", "24mm", "slow push-in", "wide environmental composition", "motivated natural light", "deep-to-medium focus", "clean cut", "curious"),
    ShotPlan("medium action", "35mm", "controlled lateral tracking", "waist-up composition with environmental context", "soft directional key light", "subject priority with gentle falloff", "match cut", "forward"),
    ShotPlan("intimate close-up", "85mm", "subtle handheld breathing", "tight face or object detail", "soft motivated side light", "shallow focus with restrained rack focus", "hard cut", "urgent"),
    ShotPlan("over-shoulder", "50mm", "slow dolly forward", "shoulder foreground with clear subject plane", "practical-light motivated contrast", "foreground soft, subject sharp", "eyeline match", "investigative"),
    ShotPlan("low-angle reveal", "35mm", "measured crane rise", "low perspective revealing scale", "rim light plus realistic ambient fill", "subject locked with environmental depth", "reveal cut", "dramatic"),
    ShotPlan("detail insert", "100mm macro", "precise focus pull", "single meaningful object or texture", "controlled practical highlight", "macro focal plane", "insert cut", "precise"),
    ShotPlan("observational profile", "50mm", "restrained sideways move", "clean profile silhouette in context", "natural window or street light", "subject sharp with soft background", "continuity cut", "calm"),
    ShotPlan("high-angle observation", "35mm", "slow descending drift", "graphic composition showing relationships", "broad natural ambient light", "layered depth", "geographic cut", "analytical"),
)


def _words(*stems: str) -> re.Pattern[str]:
    """Match each stem plus common endings (walk -> walks, walked, walking) so real narration is recognised."""
    return re.compile(r"\b(?:" + "|".join(stems) + r")(?:s|es|ed|d|ing)?\b")


CLOSE_UP = _words("close", "face", "eye", "whisper", "secret", "phone", "message", "key", "finger", "hand", "tear", "smile")
MOVEMENT = _words("enter", "walk", "run", "ran", "drive", "driv", "follow", "arriv", "leav", "move", "chas", "rush", "climb", "escap")
REVEAL = _words("reveal", "discover", "found", "sudden", "shock", "unknown", "mystery", "realiz", "surpris")
SETTING = _words("above", "map", "city", "building", "street", "room", "house", "inside", "outside", "landscape", "village")


def plan_shot(index: int, sentence: str, previous: ShotPlan | None = None) -> ShotPlan:
    """Pick a shot from what the narration beat is about, never repeating the previous shot.

    Priority: emotional detail, then movement, then a reveal, then setting; anything else rotates
    through the library so a long video still varies.
    """
    text = sentence.lower()
    if CLOSE_UP.search(text):
        base = SHOT_LIBRARY[2 if index % 3 else 5]
    elif MOVEMENT.search(text):
        base = SHOT_LIBRARY[1]
    elif REVEAL.search(text):
        base = SHOT_LIBRARY[4]
    elif SETTING.search(text):
        base = SHOT_LIBRARY[7 if index % 2 else 0]
    else:
        base = SHOT_LIBRARY[index % len(SHOT_LIBRARY)]

    if previous and base.shot == previous.shot:
        base = SHOT_LIBRARY[(SHOT_LIBRARY.index(base) + 1) % len(SHOT_LIBRARY)]
    return base


MAX_PROMPT_CHARS = 900  # Runway rejects over-long promptText; stay safely under the documented limit.

REALISM = (
    "Photorealistic live-action footage, natural anatomy and gaze, physically plausible motion, "
    "realistic lens depth of field and motion blur, subtle film grain. "
    "No text, logos, watermarks, morphing, duplicated limbs, flicker or artificial camera shake."
)


def _flat(value: object, limit: int) -> str:
    """Turn a bible entry (list, string or anything else) into short readable text."""
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v).strip() for v in value if str(v).strip())
    text = re.sub(r"\s+", " ", str(value or "")).strip().rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "..."


def build_prompt(*, visual: str, sentence: str, bible: dict[str, object], plan: ShotPlan, first: bool = False, director_note: str = "") -> str:
    """Compose a Runway prompt that always fits the length limit.

    Priority order: the visual and shot direction (what makes the clip), then the realism rules, then
    as much continuity as still fits. Continuity is trimmed first, never the shot direction.
    """
    hook = "Opening shot: instant curiosity, strong subject, purposeful movement. " if first else ""
    note = _flat(director_note, 220)
    note_text = f"Director beat: {note}. " if note else ""
    core = (
        f"{_flat(visual or sentence, 250)}. "
        f"{plan.shot}, {plan.lens} lens, {plan.framing}; camera: {plan.movement}; "
        f"lighting: {plan.lighting}; focus: {plan.focus}; mood: {plan.energy}. "
        f"{note_text}{hook}"
    )
    continuity_parts = [
        ("Subjects", _flat(bible.get("recurring_subjects", ""), 120)),
        ("Location", _flat(bible.get("recurring_locations", ""), 100)),
        ("Keep consistent", _flat(bible.get("continuity_rules", ""), 160)),
    ]
    tail = "".join(f"{label}: {text}. " for label, text in continuity_parts if text)
    room = MAX_PROMPT_CHARS - len(core) - len(REALISM) - 5  # 5 = slack for the "... " marker
    if room < len(tail):
        tail = tail[: max(room, 0)].rsplit(" ", 1)[0] + "... " if room > 40 else ""
    return (core + tail + REALISM).strip()[:MAX_PROMPT_CHARS]
