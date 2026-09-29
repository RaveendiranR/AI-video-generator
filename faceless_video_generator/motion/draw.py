"""Anti-aliased drawing primitives, easing curves and text helpers (Pillow only)."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Color = tuple[int, int, int]
Point = tuple[float, float]

SS = 4  # supersampling factor for shapes
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

_SYSTEM_FALLBACKS = (
    "arialbd.ttf",
    "Arial Bold.ttf",
    "Helvetica-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
)


# --------------------------------------------------------------------------- easing
def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    t = clamp01(t) - 1
    return 1 + t * t * ((overshoot + 1) * t + overshoot)


def seg(t: float, start: float, length: float) -> float:
    """Progress (0..1) of a segment that starts at ``start`` and lasts ``length`` seconds."""
    if length <= 0:
        return 1.0 if t >= start else 0.0
    return clamp01((t - start) / length)


def lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


# --------------------------------------------------------------------------- colour
def hex_rgb(value: str) -> Color:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"Invalid colour {value!r}; use #RRGGBB.")
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError as exc:
        raise ValueError(f"Invalid colour {value!r}; use #RRGGBB.") from exc


def mix(a: Color, b: Color, k: float) -> Color:
    """Blend ``a`` towards ``b`` by ``k`` (0 = a, 1 = b)."""
    return tuple(round(lerp(x, y, k)) for x, y in zip(a, b))  # type: ignore[return-value]


# --------------------------------------------------------------------------- fonts
@lru_cache(maxsize=None)
def resolve_font_path(weight: str = "bold", override: str | None = None) -> str | None:
    if override:
        if not Path(override).is_file():
            raise FileNotFoundError(f"Font file not found: {override}")
        return override
    bundled = FONT_DIR / ("Poppins-Medium.ttf" if weight == "medium" else "Poppins-Bold.ttf")
    if bundled.is_file():
        return str(bundled)
    for name in _SYSTEM_FALLBACKS:
        try:
            ImageFont.truetype(name, 12)
            return name
        except OSError:
            continue
    return None


@lru_cache(maxsize=512)
def get_font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(6, int(size))
    if path is None:
        return ImageFont.load_default(size)
    return ImageFont.truetype(path, size)


# --------------------------------------------------------------------------- text
@lru_cache(maxsize=1024)
def text_mask(text: str, font_path: str | None, size: int, tracking: int = 0) -> Image.Image:
    """Render text as an 'L' mask (cached; never mutate the result)."""
    font = get_font(font_path, size)
    pad = max(4, size // 6)
    advance = font.getlength(text) + tracking * max(0, len(text) - 1)
    ascent, descent = font.getmetrics()
    mask = Image.new("L", (math.ceil(advance) + 2 * pad, ascent + descent + 2 * pad), 0)
    draw = ImageDraw.Draw(mask)
    if tracking:
        x = float(pad)
        for char in text:
            draw.text((x, pad), char, font=font, fill=255)
            x += font.getlength(char) + tracking
    else:
        draw.text((pad, pad), text, font=font, fill=255)
    return mask


def text_width(text: str, font_path: str | None, size: int, tracking: int = 0) -> float:
    font = get_font(font_path, size)
    return font.getlength(text) + tracking * max(0, len(text) - 1)


def fit_size(text: str, font_path: str | None, size: int, max_width: float, tracking: int = 0) -> int:
    """Largest size <= ``size`` whose rendered width fits in ``max_width``."""
    while size > 8 and text_width(text, font_path, size, tracking) > max_width:
        size -= 2
    return size


def wrap_text(text: str, font_path: str | None, size: int, max_width: float, tracking: int = 0) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and text_width(trial, font_path, size, tracking) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def paint_mask(
    canvas: Image.Image,
    mask: Image.Image,
    color: Color,
    cx: float,
    cy: float,
    *,
    alpha: float = 1.0,
    scale: float = 1.0,
    blur: float = 0.0,
) -> None:
    """Paint ``color`` through ``mask`` centred on (cx, cy)."""
    if alpha <= 0.002 or scale <= 0.001:
        return
    if blur > 0:
        pad = math.ceil(blur * 3)
        padded = Image.new("L", (mask.width + 2 * pad, mask.height + 2 * pad), 0)
        padded.paste(mask, (pad, pad))
        mask = padded.filter(ImageFilter.GaussianBlur(blur))
    if abs(scale - 1) > 0.002:
        mask = mask.resize(
            (max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
            Image.BICUBIC,
        )
    if alpha < 0.998:
        table = [round(i * alpha) for i in range(256)]
        mask = mask.point(table)
    x = round(cx - mask.width / 2)
    y = round(cy - mask.height / 2)
    canvas.paste(color, (x, y, x + mask.width, y + mask.height), mask)


def draw_text(
    canvas: Image.Image,
    text: str,
    font_path: str | None,
    size: int,
    color: Color,
    cx: float,
    cy: float,
    *,
    tracking: int = 0,
    alpha: float = 1.0,
    scale: float = 1.0,
    blur: float = 0.0,
) -> None:
    """Draw text centred on (cx, cy); cy is the middle of the line box."""
    if not text:
        return
    paint_mask(
        canvas,
        text_mask(text, font_path, size, tracking),
        color,
        cx,
        cy,
        alpha=alpha,
        scale=scale,
        blur=blur,
    )


# --------------------------------------------------------------------------- shapes
def _paint_shape(
    canvas: Image.Image,
    bbox: tuple[float, float, float, float],
    color: Color,
    alpha: float,
    painter,
    *,
    blur: float = 0.0,
) -> None:
    """Draw with ``painter(draw, ox, oy, ss)`` on a supersampled mask, then composite."""
    if alpha <= 0.002:
        return
    pad = 3 + math.ceil(blur * 3)
    x0, y0 = math.floor(bbox[0]) - pad, math.floor(bbox[1]) - pad
    x1, y1 = math.ceil(bbox[2]) + pad, math.ceil(bbox[3]) + pad
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0 or w * h > 12_000_000:
        return
    big = Image.new("L", (w * SS, h * SS), 0)
    painter(ImageDraw.Draw(big), x0, y0, SS)
    mask = big.reduce(SS)
    if blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    if alpha < 0.998:
        mask = mask.point([round(i * alpha) for i in range(256)])
    canvas.paste(color, (x0, y0, x1, y1), mask)


def fill_circle(canvas, cx, cy, r, color, alpha=1.0, blur=0.0) -> None:
    def paint(d, ox, oy, ss):
        d.ellipse([(cx - r - ox) * ss, (cy - r - oy) * ss, (cx + r - ox) * ss, (cy + r - oy) * ss], fill=255)

    _paint_shape(canvas, (cx - r, cy - r, cx + r, cy + r), color, alpha, paint, blur=blur)


def ring(canvas, cx, cy, r, width, color, alpha=1.0) -> None:
    """Circle outline whose *outer* edge sits at radius r."""

    def paint(d, ox, oy, ss):
        box = [(cx - r - ox) * ss, (cy - r - oy) * ss, (cx + r - ox) * ss, (cy + r - oy) * ss]
        d.ellipse(box, outline=255, width=max(1, round(width * ss)))

    _paint_shape(canvas, (cx - r, cy - r, cx + r, cy + r), color, alpha, paint)


def dashed_ring(canvas, cx, cy, r, width, color, alpha=1.0, dashes=18, rotation=0.0) -> None:
    def paint(d, ox, oy, ss):
        box = [(cx - r - ox) * ss, (cy - r - oy) * ss, (cx + r - ox) * ss, (cy + r - oy) * ss]
        step = 360 / dashes
        for i in range(dashes):
            start = rotation + i * step
            d.arc(box, start, start + step * 0.5, fill=255, width=max(1, round(width * ss)))

    _paint_shape(canvas, (cx - r, cy - r, cx + r, cy + r), color, alpha, paint)


def arc(canvas, cx, cy, r, width, start_deg, sweep_deg, color, alpha=1.0) -> None:
    """Round-capped arc; angles in degrees, 0 = 3 o'clock, clockwise positive (screen space)."""
    if abs(sweep_deg) < 0.5:
        return
    points = arc_points(cx, cy, r, math.radians(start_deg), math.radians(start_deg + sweep_deg), 96)
    polyline(canvas, points, width, color, alpha)


def arc_points(cx, cy, r, a0, a1, count) -> list[Point]:
    return [
        (cx + r * math.cos(a0 + (a1 - a0) * i / count), cy + r * math.sin(a0 + (a1 - a0) * i / count))
        for i in range(count + 1)
    ]


def polyline(canvas, points: Sequence[Point], width, color, alpha=1.0) -> None:
    if len(points) < 2:
        return
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    half = width / 2

    def paint(d, ox, oy, ss):
        pts = [((x - ox) * ss, (y - oy) * ss) for x, y in points]
        d.line(pts, fill=255, width=max(1, round(width * ss)))
        for x, y in (pts[0], pts[-1]):
            rr = half * ss
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
        # Round joins: a disc on every interior vertex keeps sharp curves smooth.
        for x, y in pts[1:-1]:
            rr = half * ss
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)

    _paint_shape(canvas, (min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half), color, alpha, paint)


def polygon(canvas, points: Sequence[Point], color, alpha=1.0, blur=0.0) -> None:
    if len(points) < 3:
        return
    xs, ys = [p[0] for p in points], [p[1] for p in points]

    def paint(d, ox, oy, ss):
        d.polygon([((x - ox) * ss, (y - oy) * ss) for x, y in points], fill=255)

    _paint_shape(canvas, (min(xs), min(ys), max(xs), max(ys)), color, alpha, paint, blur=blur)


def rounded_rect(canvas, box, radius, color, alpha=1.0, outline_width=0) -> None:
    x0, y0, x1, y1 = box

    def paint(d, ox, oy, ss):
        rect = [(x0 - ox) * ss, (y0 - oy) * ss, (x1 - ox) * ss, (y1 - oy) * ss]
        if outline_width:
            d.rounded_rectangle(rect, radius * ss, outline=255, width=max(1, round(outline_width * ss)))
        else:
            d.rounded_rectangle(rect, radius * ss, fill=255)

    _paint_shape(canvas, (x0, y0, x1, y1), color, alpha, paint)


def arrow_head(canvas, tip: Point, angle: float, size: float, color, alpha=1.0) -> None:
    """Filled arrow head with its tip at ``tip`` pointing along ``angle`` (radians)."""
    left = (tip[0] - size * math.cos(angle - 0.5), tip[1] - size * math.sin(angle - 0.5))
    right = (tip[0] - size * math.cos(angle + 0.5), tip[1] - size * math.sin(angle + 0.5))
    polygon(canvas, [tip, left, right], color, alpha)


def star_points(cx, cy, r_outer, r_inner=None, points=5, rotation=-math.pi / 2) -> list[Point]:
    r_inner = r_inner if r_inner is not None else r_outer * 0.45
    out: list[Point] = []
    for i in range(points * 2):
        radius = r_outer if i % 2 == 0 else r_inner
        angle = rotation + i * math.pi / points
        out.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return out
