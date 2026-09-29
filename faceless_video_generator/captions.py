from __future__ import annotations

from typing import Iterator


def chunk_words(sentence: str, max_words: int = 4, max_chars: int = 24) -> list[str]:
    """Split a sentence into short, readable caption chunks."""
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in sentence.split():
        trial = current + [word]
        if current and (len(trial) > max_words or len(" ".join(trial)) > max_chars):
            chunks.append(current)
            current = [word]
        else:
            current = trial
        if word[-1] in ",;:\u2014" and len(current) >= 2:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return [" ".join(chunk) for chunk in chunks]


def timed_chunks(
    sentence: str, start: float, duration: float, tail_padding: float = 0.0
) -> Iterator[tuple[float, float, str]]:
    """Spread chunks across the spoken part of a scene, weighted by length."""
    chunks = chunk_words(sentence) or [sentence]
    weights = [len(chunk) + 1 for chunk in chunks]
    total = float(sum(weights))
    speech = max(0.2, duration - tail_padding)
    cursor = start
    for number, (chunk, weight) in enumerate(zip(chunks, weights)):
        end = cursor + speech * weight / total
        if number == len(chunks) - 1:
            end = start + duration
        yield cursor, end, chunk
        cursor = end


def ass_time(seconds: float) -> str:
    centis = max(0, int(round(seconds * 100)))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(
    scenes: list[dict[str, object]],
    *,
    width: int,
    height: int,
    font_size: int = 0,
    margin_v: int = 0,
    tail_padding: float = 0.25,
    uppercase: bool = True,
) -> str:
    """Build an ASS subtitle file with large, animated caption chunks."""
    font_size = font_size or max(24, round(height * 0.042))
    margin_v = margin_v or round(height * 0.22)
    side = round(width * 0.08)
    outline = max(2, round(font_size * 0.09))
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},2,2,{side},{side},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines: list[str] = []
    cursor = 0.0
    for scene in scenes:
        duration = float(scene["duration"])
        for start, end, chunk in timed_chunks(
            str(scene["sentence"]), cursor, duration, tail_padding
        ):
            text = _escape(chunk.upper() if uppercase else chunk)
            pop = "{\\fscx88\\fscy88\\t(0,110,\\fscx100\\fscy100)}"
            lines.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{pop}{text}"
            )
        cursor += duration
    return header + "\n".join(lines) + "\n"