"""Animated scene templates. Each ``render_*`` paints one frame at time ``t`` (seconds).

Layout is expressed in a 1080x1920 design space and scaled by ``Ctx.u``, so the same
templates work at any resolution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from PIL import Image

from . import draw as D
from .spec import Theme


@dataclass(frozen=True)
class Ctx:
    w: int
    h: int
    font_bold: str | None
    font_medium: str | None

    @property
    def u(self) -> float:
        """Design-unit scale: 1.0 at 1080x1920."""
        return min(self.w / 1080, self.h / 1920)

    def size(self, units: float) -> int:
        return max(8, round(units * self.u))


# ------------------------------------------------------------------ shared pieces
def pill(canvas: Image.Image, ctx: Ctx, th: Theme, text: str, cx: float, cy: float, alpha: float = 1.0, scale: float = 1.0) -> None:
    if not text or alpha <= 0:
        return
    u = ctx.u
    size, tracking = ctx.size(23), max(1, round(4 * u))
    tw = D.text_width(text, ctx.font_bold, size, tracking)
    w, h = (tw + 64 * u) * scale, 58 * u * scale
    D.rounded_rect(canvas, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), h / 2, th.pill_bg, alpha)
    D.draw_text(canvas, text, ctx.font_bold, size, th.pill_fg, cx, cy + 1, tracking=tracking, alpha=alpha, scale=scale)


def spinner(canvas: Image.Image, ctx: Ctx, color: D.Color, cx: float, cy: float, t: float, alpha: float) -> None:
    u = ctx.u
    D.arc(canvas, cx, cy, 30 * u, 8 * u, t * 400 - 90, 270, color, alpha)


def reveal(t: float, start: float, length: float = 0.4) -> tuple[float, float]:
    """Return (alpha, rise-offset factor 1..0) for a fade-and-rise entrance."""
    p = D.ease_out_cubic(D.seg(t, start, length))
    return p, 1 - p


def stagger(count: int, duration: float, first: float = 0.18, spread: float = 0.55) -> float:
    return min(0.45, duration * spread / max(1, count))


def _breathe(t: float, duration: float) -> float:
    """Slow scale drift so held text never looks frozen."""
    return 1 + 0.025 * D.clamp01(t / max(duration, 0.1))


# ------------------------------------------------------------------ icons
def draw_icon(canvas: Image.Image, name: str, cx: float, cy: float, size: float, color: D.Color, alpha: float, t: float) -> None:
    half = size / 2
    lw = max(2.0, size * 0.11)
    if name == "spark":
        spin = t * 25
        for k in range(8):
            a = math.radians(spin + k * 45)
            p0 = (cx + math.cos(a) * half * 0.42, cy + math.sin(a) * half * 0.42)
            p1 = (cx + math.cos(a) * half * 1.0, cy + math.sin(a) * half * 1.0)
            D.polyline(canvas, [p0, p1], lw, color, alpha)
    elif name == "cycle":
        D.arc(canvas, cx, cy, half * 0.78, lw, -60, 290, color, alpha)
        end = math.radians(-60 + 290)
        tip = (cx + half * 0.78 * math.cos(end), cy + half * 0.78 * math.sin(end))
        D.arrow_head(canvas, tip, end + math.pi / 2, half * 0.85, color, alpha)
    elif name == "star":
        pts = D.star_points(cx, cy + size * 0.04, half * 1.05, half * 0.46)
        D.polyline(canvas, pts + [pts[0], pts[1]], lw, color, alpha)
    elif name == "check":
        D.polyline(canvas, [(cx - half * 0.7, cy + half * 0.05), (cx - half * 0.2, cy + half * 0.55), (cx + half * 0.8, cy - half * 0.5)], lw * 1.2, color, alpha)
    elif name == "bolt":
        pts = [(0.15, -1.0), (-0.65, 0.15), (-0.05, 0.15), (-0.2, 1.0), (0.65, -0.2), (0.05, -0.2)]
        D.polygon(canvas, [(cx + x * half, cy + y * half) for x, y in pts], color, alpha)
    else:  # dot
        D.fill_circle(canvas, cx, cy, half * 0.5, color, alpha)


# ------------------------------------------------------------------ hook
def render_hook(canvas: Image.Image, sc: dict[str, Any], t: float, ctx: Ctx, th: Theme) -> None:
    u, w, h, dur = ctx.u, ctx.w, ctx.h, sc["duration"]
    items: list[tuple[str, D.Color, int]] = []
    for text in sc["lines"]:
        items.append((text, th.fg, D.fit_size(text, ctx.font_bold, ctx.size(92), w * 0.88)))
    if sc["accent"]:
        items.append((sc["accent"], th.accent, D.fit_size(sc["accent"], ctx.font_bold, ctx.size(132), w * 0.9)))
    heights = [round(size * 1.2) for _, _, size in items]
    total = sum(heights)
    top = h * 0.47 - total / 2
    cx = w / 2
    step = stagger(len(items), dur)
    breathe = _breathe(t, dur)

    if sc["tag"]:
        a, rise = reveal(t, 0.0, 0.35)
        pill(canvas, ctx, th, sc["tag"], cx, top - 62 * u + rise * 14 * u, a)
    y = top
    for i, ((text, color, size), lh) in enumerate(zip(items, heights)):
        start = 0.15 + i * step
        a, rise = reveal(t, start, 0.4)
        is_accent = sc["accent"] and i == len(items) - 1
        pop = 0.86 + 0.14 * D.ease_out_back(D.seg(t, start, 0.5)) if is_accent else 1.0
        D.draw_text(canvas, text, ctx.font_bold, size, color, cx, y + lh / 2 + rise * 30 * u, alpha=a, scale=pop * breathe)
        y += lh


# ------------------------------------------------------------------ kinetic word
def render_kinetic(canvas: Image.Image, sc: dict[str, Any], t: float, ctx: Ctx, th: Theme) -> None:
    u, w, h, dur = ctx.u, ctx.w, ctx.h, sc["duration"]
    cx = w / 2
    if sc["small"]:
        size = D.fit_size(sc["small"], ctx.font_bold, ctx.size(72), w * 0.8)
        a, rise = reveal(t, 0.05, 0.3)
        D.draw_text(canvas, sc["small"], ctx.font_bold, size, th.muted, cx, h * 0.435 + rise * 20 * u, alpha=a)
    big = sc["big"]
    size = D.fit_size(big, ctx.font_bold, ctx.size(230), w * 0.9)
    p = D.seg(t, 0.2, 0.5)
    pop = 0.7 + 0.3 * D.ease_out_back(p, 2.2)
    drift = 1 + 0.05 * D.clamp01(t / dur)
    a = D.clamp01(D.seg(t, 0.2, 0.2))
    y = h * 0.51
    D.draw_text(canvas, big, ctx.font_bold, size, (0, 0, 0), cx, y + 10 * u, alpha=a * 0.45, scale=pop * drift, blur=14 * u)
    D.draw_text(canvas, big, ctx.font_bold, size, th.fg, cx, y, alpha=a, scale=pop * drift)
    if sc["spinner"]:
        spinner(canvas, ctx, th.accent, cx, h * 0.605, t, D.seg(t, 0.6, 0.3))


# ------------------------------------------------------------------ steps / loop diagram
def _node_layout(count: int, ctx: Ctx) -> tuple[float, float, float, float]:
    u = ctx.u
    radius = 309 * u if count >= 3 else 250 * u
    return ctx.w / 2, ctx.h * 0.464, radius, 124 * u


def _node_angle(index: int, count: int) -> float:
    return math.radians(-90 + 360 * index / count)


def _draw_arrow(canvas, ctx, cx, cy, radius, node_r, a_from, a_to, progress, color, alpha=1.0) -> None:
    u = ctx.u
    margin = (node_r + 14 * u) / radius
    start = a_from + margin
    end = a_to - margin
    if end <= start:
        return
    head = 26 * u
    tip_angle = start + (end - start) * D.clamp01(progress)
    if progress <= 0.02:
        return
    line_end = tip_angle - (head * 0.7) / radius if progress > 0.06 else tip_angle
    pts = D.arc_points(cx, cy, radius, start, max(start, line_end), 80)
    D.polyline(canvas, pts, 6 * u, color, alpha)
    if progress > 0.06:
        tip = (cx + radius * math.cos(tip_angle), cy + radius * math.sin(tip_angle))
        D.arrow_head(canvas, tip, tip_angle + math.pi / 2, head, color, alpha)


def render_steps(canvas: Image.Image, sc: dict[str, Any], t: float, ctx: Ctx, th: Theme) -> None:
    u, w, h, dur = ctx.u, ctx.w, ctx.h, sc["duration"]
    nodes = sc["nodes"]
    n = len(nodes)
    cx, cy, radius, node_r = _node_layout(n, ctx)
    lead = 0.3
    slot = max(0.4, (dur - lead - 0.2) / n)
    starts = [lead + i * slot for i in range(n)]
    active = max((i for i, s in enumerate(starts) if t >= s), default=-1)
    placeholder = D.mix(th.bg, th.muted, 0.45)

    if sc["tag"]:
        a, rise = reveal(t, 0.0, 0.3)
        pill(canvas, ctx, th, sc["tag"], w / 2, h * 0.09 + rise * 10 * u, a)
    if active >= 0:
        title = nodes[active]["title"]
        size = D.fit_size(title, ctx.font_bold, ctx.size(66), w * 0.9)
        a, rise = reveal(t, starts[active], 0.3)
        D.draw_text(canvas, title, ctx.font_bold, size, th.fg, w / 2, h * 0.142 + rise * 16 * u, alpha=a)

    # Placeholders for nodes that have not appeared yet.
    for i in range(n):
        if t < starts[i] + (0.32 * slot if i else 0.0):
            ang = _node_angle(i, n)
            px, py = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
            D.dashed_ring(canvas, px, py, node_r * 0.86, 3 * u, placeholder, 0.9, rotation=t * 12)

    # Connecting arrows (older ones settle to the text colour, the newest is accent).
    for i in range(1, n):
        prog = D.ease_in_out(D.seg(t, starts[i], 0.4 * slot))
        color = th.accent if i == active else th.fg
        _draw_arrow(canvas, ctx, cx, cy, radius, node_r, _node_angle(i - 1, n), _node_angle(i, n), prog, color)
    if sc["loop"] and n >= 3:
        close_start = starts[-1] + 0.5 * slot
        prog = D.ease_in_out(D.seg(t, close_start, 0.4 * slot))
        _draw_arrow(canvas, ctx, cx, cy, radius, node_r, _node_angle(n - 1, n), _node_angle(0, n) + 2 * math.pi, prog, th.accent)

    # Nodes.
    for i, node in enumerate(nodes):
        appear = starts[i] + (0.32 * slot if i else 0.0)
        p = D.seg(t, appear, 0.4)
        if p <= 0:
            continue
        scale = 0.4 + 0.6 * D.ease_out_back(p, 1.9)
        a = D.clamp01(p * 2.5)
        ang = _node_angle(i, n)
        nx, ny = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
        r = node_r * scale
        is_active = i == active
        edge = th.accent if is_active else th.fg
        D.fill_circle(canvas, nx, ny + 12 * u, r, th.accent if is_active else (0, 0, 0), a * (0.28 if is_active else 0.10), blur=16 * u)
        D.fill_circle(canvas, nx, ny, r, th.node_fill, a)
        D.ring(canvas, nx, ny, r, 5 * u * scale, edge, a)
        label_size = D.fit_size(node["label"], ctx.font_bold, ctx.size(33), node_r * 1.55)
        draw_icon(canvas, node["icon"], nx, ny - 0.36 * r, 0.36 * r * 1.4, edge, a, t)
        D.draw_text(canvas, node["label"], ctx.font_bold, label_size, edge, nx, ny + 0.16 * r, alpha=a, scale=scale)
        if node["sub"]:
            sub_size = D.fit_size(node["sub"], ctx.font_medium, ctx.size(17), node_r * 1.5, 1)
            D.draw_text(canvas, node["sub"], ctx.font_medium, sub_size, th.muted, nx, ny + 0.5 * r, tracking=1, alpha=a, scale=scale)


# ------------------------------------------------------------------ chart + big number
def curve_value(kind: str, x: float) -> float:
    if kind == "linear":
        return x
    if kind == "log":
        return math.log1p(9 * x) / math.log(10)
    if kind == "s":
        lo, hi = 1 / (1 + math.exp(5)), 1 / (1 + math.exp(-5))
        return (1 / (1 + math.exp(-10 * (x - 0.5))) - lo) / (hi - lo)
    return (math.exp(5 * x) - 1) / (math.exp(5) - 1)


def render_chart(canvas: Image.Image, sc: dict[str, Any], t: float, ctx: Ctx, th: Theme) -> None:
    u, w, h, dur = ctx.u, ctx.w, ctx.h, sc["duration"]
    cx = w / 2
    if sc["tag"]:
        a, rise = reveal(t, 0.0, 0.3)
        pill(canvas, ctx, th, sc["tag"], cx, h * 0.082 + rise * 10 * u, a)

    show = sc["show_curve"]
    if sc["title"]:
        size = ctx.size(62)
        lines = D.wrap_text(sc["title"], ctx.font_bold, size, w * 0.84)
        while len(lines) > 3 and size > ctx.size(36):
            size -= 2
            lines = D.wrap_text(sc["title"], ctx.font_bold, size, w * 0.84)
        a, rise = reveal(t, 0.12, 0.4)
        top = h * (0.128 if show else 0.30)
        for i, line in enumerate(lines):
            D.draw_text(canvas, line, ctx.font_bold, size, th.fg, cx, top + (i + 0.5) * size * 1.22 + rise * 18 * u, alpha=a)

    draw_time = min(2.0, max(0.8, dur * 0.42))
    curve_start = 0.35
    curve_done = curve_start + draw_time
    if show:
        x0, x1 = w * 0.062, w * 0.938
        y0, y1 = h * 0.262, h * 0.534
        pa = D.ease_out_cubic(D.seg(t, 0.1, 0.4))
        D.rounded_rect(canvas, (x0, y0, x1, y1), 28 * u, th.panel, pa)
        D.rounded_rect(canvas, (x0, y0, x1, y1), 28 * u, D.mix(th.panel, (255, 255, 255), 0.07), pa * 0.9, outline_width=2 * u)
        px0, px1 = x0 + 48 * u, x1 - 48 * u
        base, top = y1 - 92 * u, y0 + 64 * u
        grid = D.mix(th.panel, (255, 255, 255), 0.06)
        for k in (1, 2, 3):
            gy = base - (base - top) * k / 3.4
            D.polyline(canvas, [(px0, gy), (px1, gy)], 2 * u, grid, pa)
        D.polyline(canvas, [(px0, base), (px1, base)], 3 * u, D.mix(th.panel, (255, 255, 255), 0.22), pa)
        labels = sc["x_labels"]
        for i, label in enumerate(labels):
            lx = px0 + (px1 - px0) * i / max(1, len(labels) - 1)
            last = i == len(labels) - 1
            anchor = lx - 18 * u if last else lx + 18 * u if i == 0 and len(labels) > 1 else lx
            D.draw_text(canvas, label, ctx.font_bold, ctx.size(22), th.accent if last else th.muted, anchor, base + 42 * u, tracking=max(1, round(2 * u)), alpha=pa)
        prog = D.ease_in_out(D.seg(t, curve_start, draw_time))
        if prog > 0.005:
            count = 120
            upto = max(2, round(count * prog))
            pts = []
            for i in range(upto + 1):
                x = min(prog, i / count) if i == upto else i / count
                pts.append((px0 + (px1 - px0) * x, base - (base - top) * curve_value(sc["curve"], x)))
            D.polygon(canvas, pts + [(pts[-1][0], base), (pts[0][0], base)], th.accent, 0.13)
            D.polyline(canvas, pts, 7 * u, th.accent)
            tip = pts[-1]
            D.fill_circle(canvas, tip[0], tip[1], 26 * u, th.accent, 0.35, blur=10 * u)
            D.fill_circle(canvas, tip[0], tip[1], 13 * u, (255, 255, 255))
            D.ring(canvas, tip[0], tip[1], 13 * u, 4 * u, th.accent)

    if sc["value"]:
        vstart = curve_done if show else 0.35
        p = D.seg(t, vstart, 0.55)
        if p > 0:
            size = D.fit_size(sc["value"], ctx.font_bold, ctx.size(240), w * 0.8)
            vy = h * (0.612 if show else 0.5)
            pop = 0.6 + 0.4 * D.ease_out_back(p, 2.0)
            a = D.clamp01(p * 3)
            D.draw_text(canvas, sc["value"], ctx.font_bold, size, th.accent, cx, vy, alpha=a * 0.55, scale=pop, blur=20 * u)
            D.draw_text(canvas, sc["value"], ctx.font_bold, size, th.accent, cx, vy, alpha=a, scale=pop)
            if sc["caption"]:
                ca, rise = reveal(t, vstart + 0.25, 0.4)
                D.draw_text(canvas, sc["caption"], ctx.font_bold, ctx.size(28), th.muted, cx, vy + size * 0.78 + rise * 12 * u, tracking=max(1, round(5 * u)), alpha=ca)


# ------------------------------------------------------------------ outro
def render_outro(canvas: Image.Image, sc: dict[str, Any], t: float, ctx: Ctx, th: Theme) -> None:
    u, w, h, dur = ctx.u, ctx.w, ctx.h, sc["duration"]
    cx = w / 2
    size = ctx.size(92)
    rows: list[tuple[str, D.Color]] = []
    palette = [th.fg, th.second]
    for i, line in enumerate(sc["lines"]):
        for part in D.wrap_text(line, ctx.font_bold, size, w * 0.86) or [line]:
            rows.append((part, palette[i % 2]))
    line_h = round(size * 1.2)
    total = line_h * len(rows)
    top = h * 0.44 - total / 2
    step = stagger(len(rows), dur)
    breathe = _breathe(t, dur)
    if sc["tag"]:
        a, rise = reveal(t, 0.0, 0.3)
        pill(canvas, ctx, th, sc["tag"], cx, top - 62 * u + rise * 12 * u, a)
    for i, (text, color) in enumerate(rows):
        fit = D.fit_size(text, ctx.font_bold, size, w * 0.9)
        a, rise = reveal(t, 0.2 + i * step, 0.4)
        D.draw_text(canvas, text, ctx.font_bold, fit, color, cx, top + (i + 0.5) * line_h + rise * 30 * u, alpha=a, scale=breathe)
    if sc["spinner"]:
        spinner(canvas, ctx, th.fg, cx, top + total + 92 * u, t, D.seg(t, 0.5 + step * len(rows), 0.3))


RENDERERS: dict[str, Callable[[Image.Image, dict[str, Any], float, Ctx, Theme], None]] = {
    "hook": render_hook,
    "kinetic": render_kinetic,
    "steps": render_steps,
    "chart": render_chart,
    "outro": render_outro,
}
