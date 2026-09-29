"""Procedural motion-graphics videos: animated typography, diagrams and charts.

Unlike the photo pipeline this needs no image-generation service: every frame is drawn
locally, so renders are free, fast, deterministic and work offline.
"""

from .planner import PlanError, plan_from_script, plan_from_script_ai, plan_from_topic, plan_script, script_fidelity
from .render import MotionRenderError, render_previews, render_video
from .spec import DEMO_SPEC, SpecError, normalize_spec

__all__ = [
    "DEMO_SPEC",
    "MotionRenderError",
    "PlanError",
    "SpecError",
    "normalize_spec",
    "plan_from_script",
    "plan_from_script_ai",
    "plan_from_topic",
    "plan_script",
    "render_previews",
    "render_video",
    "script_fidelity",
]
