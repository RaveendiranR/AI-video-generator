from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

from .online_ai import OnlineAIError, generate_text

LOGGER = logging.getLogger("faceless_video_generator")

_LABEL_LINE = re.compile(
    r"^\s*(?:paragraph|section|part|chapter|scene|segment|act|step|point)\s*\d+\s*[:.\-\u2013\u2014].*$",
    re.IGNORECASE,
)
_BOLD_HEADING = re.compile(r"^(?:\*\*|__)[^*_]+(?:\*\*|__):?$")
_WORD_COUNT = re.compile(r"[\(\[]\s*\d+\s*words?\s*[\)\]]", re.IGNORECASE)
_BRACKETED = re.compile(r"\[[^\]]*\]")
_LEADING_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.)]\s+")
_INLINE_NUMBER = re.compile(r"(?<=[.!?])\s+\d{1,3}\s*[.)]\s+(?=[A-Z])")


def clean_narration(text: str) -> str:
    """Strip model artifacts (word counts, labels, numbering, markdown) from narration.

    Text models often add things like ``(13 words)``, ``Paragraph 4: Title`` or
    ``13.`` numbering, sometimes as literal backslash-n sequences. Spoken aloud these
    break the voice step, so only clean sentences are kept.
    """
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WORD_COUNT.sub(" ", text)
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _BOLD_HEADING.match(stripped):
            stripped = ""
        stripped = re.sub(r"^[*_`]+|[*_`]+$", "", stripped).strip()
        if not stripped or _LABEL_LINE.match(stripped) or stripped.startswith("#"):
            kept.append("")
            continue
        stripped = _LEADING_NUMBER.sub("", stripped)
        stripped = re.sub(r"^[\-*\u2022]\s+", "", stripped)
        kept.append(stripped)
    text = " ".join(part for part in kept if part)
    text = _BRACKETED.sub(" ", text)
    text = _INLINE_NUMBER.sub(" ", text)
    text = re.sub(r"[*_`#]+", "", text)
    text = text.replace("\\", " ")
    return re.sub(r"\s+", " ", text).strip()


def _complete(prompt: str, provider: str, model: str, hf_token: str | None) -> str:
    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for the Groq provider.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the optional Groq provider with: pip install 'openai>=1.0'") from exc
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
        return (response.choices[0].message.content or "").strip()
    try:
        return generate_text(prompt, provider=provider, model=model, hf_token=hf_token)
    except OnlineAIError as exc:
        raise RuntimeError(str(exc)) from exc


def _complete_with_retry(
    prompt: str, provider: str, model: str, hf_token: str | None, attempts: int = 3
) -> str:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            text = _complete(prompt, provider, model, hf_token)
            if text.strip():
                return text
            last = RuntimeError("empty response")
        except RuntimeError as exc:
            last = exc
            if re.search(r"\((?:400|401|403|404)\)", str(exc)):
                break  # bad key or bad request: retrying cannot help
        if attempt < attempts:
            time.sleep(4 * attempt)
    raise RuntimeError(str(last))


def _section_titles(topic: str, count: int, provider: str, model: str, hf_token: str | None) -> list[str]:
    prompt = (
        f"Plan a {count}-part narration for a faceless YouTube video about: {topic}. "
        "Part 1 is a curiosity-driven hook, the last part is a memorable conclusion, and the parts in "
        "between each cover one distinct idea with examples. "
        f"Return ONLY a JSON array of exactly {count} short part titles."
    )
    try:
        raw = _complete_with_retry(prompt, provider, model, hf_token, attempts=2)
        start, end = raw.find("["), raw.rfind("]")
        titles = json.loads(raw[start : end + 1])
        if isinstance(titles, list) and len(titles) == count:
            return [str(title).strip() for title in titles]
    except (RuntimeError, ValueError):
        pass
    middle = [f"Key idea {i}" for i in range(1, count - 1)]
    return ["Hook and why it matters", *middle, "Conclusion and takeaway"]


def write_script(
    topic: str,
    *,
    provider: str = "pollinations",
    model: str = "openai",
    seconds: int = 60,
    hf_token: str | None = None,
) -> str:
    """Generate narration with an online text model.

    Videos over two minutes are written section by section, because a single
    request rarely produces more than a few hundred words.
    """
    target_words = max(80, round(seconds * 2.35))
    if seconds <= 120:
        prompt = (
            "Write an engaging narration for a faceless YouTube video. "
            f"Topic: {topic}. Target duration: {seconds} seconds, approximately {target_words} spoken words. "
            "Start with a hook that creates curiosity in the first sentence. "
            "Use short spoken sentences of 8 to 16 words, concrete details or examples instead of generalities, "
            "and end with a memorable closing line. "
            "Return only plain narration sentences: no headings, labels, numbering, word counts, bullets, "
            "stage directions, sound effects, or quotation marks."
        )
        text = clean_narration(_complete_with_retry(prompt, provider, model, hf_token))
    else:
        text = _write_long_script(topic, target_words, seconds, provider, model, hf_token)
    if not text:
        raise RuntimeError("The script model returned an empty response.")
    return text


def _write_long_script(
    topic: str, target_words: int, seconds: int, provider: str, model: str, hf_token: str | None
) -> str:
    count = max(3, min(14, round(seconds / 60)))
    per_section = round(target_words / count)
    titles = _section_titles(topic, count, provider, model, hf_token)
    outline = "; ".join(f"{i}. {title}" for i, title in enumerate(titles, 1))
    parts: list[str] = []
    for index, title in enumerate(titles, 1):
        LOGGER.info("Writing script part %d/%d: %s", index, count, title)
        if index == 1:
            role = "Open with a hook that creates curiosity in the first sentence. "
        elif index == count:
            role = "Finish with a memorable closing line. "
        else:
            role = "Do not greet the viewer and do not summarize or conclude the video. "
        earlier = f"The previous part ended with: {parts[-1][-300:]} " if parts else ""
        prompt = (
            f"You are writing part {index} of {count} of the narration for a faceless YouTube video about: {topic}. "
            f"Full outline: {outline}. Write ONLY part {index}, titled '{title}', "
            f"about {per_section} spoken words. Use short spoken sentences of 8 to 16 words, concrete "
            f"details, numbers and examples. {role}{earlier}Do not repeat earlier points. "
            "Return only plain narration sentences: no headings, labels, numbering, word counts, bullets, "
            "stage directions, sound effects, or quotation marks."
        )
        try:
            section = clean_narration(_complete_with_retry(prompt, provider, model, hf_token))
        except RuntimeError as exc:
            if not parts:
                raise
            LOGGER.warning("Skipping script part %d after repeated failures: %s", index, exc)
            continue
        if section:
            parts.append(section)
        time.sleep(2)
    return " ".join(parts)


def _story_excerpt(sentences: list[str], limit: int = 18000) -> str:
    """Keep the beginning, middle, and ending of long scripts for story analysis."""
    text = " ".join(sentences)
    if len(text) <= limit:
        return text
    part = limit // 3
    return f"{text[:part]}\n...[middle of narration omitted]...\n{text[-part:]}"


def _json_object(raw: str) -> dict[str, object]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError("story analysis model did not return a JSON object")
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("story analysis model returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("story analysis model returned a non-object")
    return value


def analyze_story(
    sentences: list[str],
    *,
    image_style: str = "",
    provider: str = "pollinations",
    model: str = "openai",
    hf_token: str | None = None,
) -> dict[str, object]:
    """Read the narration as one story and create a reusable visual bible.

    The bible is intentionally separate from individual image prompts. It gives
    every later scene the same subjects, locations, palette, lighting, and camera
    language instead of asking an image model to infer continuity from one line.
    """
    fallback: dict[str, object] = {
        "story_summary": "A coherent documentary story told through realistic, grounded scenes.",
        "visual_bible": {
            "overall_style": image_style or "photorealistic documentary photography",
            "color_palette": "natural neutrals with restrained cinematic contrast",
            "lighting": "motivated natural light with realistic shadows",
            "camera_language": "observational wides, medium action shots, detail inserts, restrained handheld movement",
            "recurring_subjects": [],
            "recurring_locations": [],
            "continuity_rules": [
                "Keep recurring subjects, locations, weather, season, and time period consistent.",
                "Use believable materials, anatomy, scale, perspective, and physical cause and effect.",
            ],
        },
    }
    if not sentences:
        return fallback

    story = _story_excerpt(sentences)
    prompt = (
        "Read this entire narration as one story before planning any images. "
        "Create a visual bible for a premium faceless documentary. Identify recurring people, objects, "
        "locations, time period, weather, and visual motifs only when the narration supports them. "
        "Do not invent a celebrity or a specific real person. Define how the story should look consistently "
        "from beginning to end. Return ONLY JSON with this shape: "
        '{"story_summary":"...", "visual_bible":{"overall_style":"...", "color_palette":"...", '
        '"lighting":"...", "camera_language":"...", "recurring_subjects":["..."], '
        '"recurring_locations":["..."], "continuity_rules":["..."]}}. '
        f"Base style preference: {image_style or 'photorealistic documentary photography'}.\n\n"
        f"FULL NARRATION:\n{story}"
    )
    try:
        result = _json_object(_complete_with_retry(prompt, provider, model, hf_token, attempts=3))
    except RuntimeError as exc:
        LOGGER.warning("Story visual bible unavailable (%s); using deterministic continuity rules.", exc)
        return fallback

    bible = result.get("visual_bible")
    if not isinstance(bible, dict):
        result["visual_bible"] = fallback["visual_bible"]
    else:
        for key, default in fallback["visual_bible"].items():
            if not bible.get(key):
                bible[key] = default
    if not result.get("story_summary"):
        result["story_summary"] = fallback["story_summary"]
    return result


def write_storyboard(
    sentences: list[str],
    *,
    image_style: str = "",
    provider: str = "pollinations",
    model: str = "openai",
    hf_token: str | None = None,
    batch_size: int = 8,
    attempts: int = 3,
) -> dict[str, object]:
    """Analyze the whole narration, then write continuity-aware scene prompts."""
    context = analyze_story(
        sentences,
        image_style=image_style,
        provider=provider,
        model=model,
        hf_token=hf_token,
    )
    prompts = write_visual_prompts(
        sentences,
        provider=provider,
        model=model,
        hf_token=hf_token,
        batch_size=batch_size,
        attempts=attempts,
        story_context=context,
    )
    return {"storyboard": context, "prompts": prompts}



def plan_cinematic_storyboard(
    sentences: list[str],
    *,
    image_style: str = "",
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-6",
    hf_token: str | None = None,
) -> dict[str, object]:
    """Use one full-story director pass to produce a compact visual bible and per-scene beats.

    The output is deliberately structured and compact so the video renderer can turn it into short,
    provider-safe prompts without repeatedly asking the model to rediscover continuity.
    """
    if not sentences:
        return {"storyboard": {"story_summary": "", "visual_bible": {}}, "scenes": []}
    story = _story_excerpt(sentences, limit=16000)
    request = {
        "story_summary": "brief summary",
        "visual_bible": {
            "overall_style": "...",
            "palette": "...",
            "lighting": "...",
            "subjects": ["..."],
            "locations": ["..."],
            "continuity": ["..."],
        },
        "scenes": [
            {
                "index": 1,
                "visual": "concrete filmable visual, 8-22 words",
                "beat": "what changes or moves, 6-18 words",
                "shot": "wide|medium|close|over_shoulder|detail|low_angle|high_angle|tracking",
                "transition": "cut|match|reveal|insert|dissolve",
                "energy": "calm|curious|urgent|tense|warm|shocking",
            }
        ],
    }
    prompt = (
        "You are the lead director for a premium photorealistic faceless YouTube film. "
        "Read the COMPLETE narration as one story. Build continuity first, then direct every scene. "
        "Do not invent unsupported people, locations, brands, dates, or celebrity likenesses. "
        "Avoid generic stock-photo staging. Prefer motivated actions, believable environments, purposeful framing, "
        "and camera movement that visually explains the narration. Vary shot scale and transition grammar. "
        "The first scene must create immediate visual curiosity; the last should feel like a deliberate ending. "
        "Return ONLY valid JSON with exactly this structure, and exactly one scene object for every numbered narration line. "
        "Keep each visual/beat concise so another system can turn it into a short video prompt. "
        f"Style preference: {image_style or 'photorealistic cinematic documentary'}\n\n"
        f"REQUIRED SHAPE:\n{json.dumps(request, ensure_ascii=False)}\n\n"
        f"NUMBERED NARRATION:\n" + "\n".join(f"{i+1}. {text}" for i, text in enumerate(sentences)) +
        "\n\nFULL STORY EXCERPT:\n" + story
    )
    raw = _complete_with_retry(prompt, provider, model, hf_token, attempts=3)
    result = _json_object(raw)
    scenes = result.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != len(sentences):
        raise RuntimeError("cinematic director returned the wrong number of scene directives")
    cleaned: list[dict[str, object]] = []
    for i, item in enumerate(scenes):
        if not isinstance(item, dict):
            raise RuntimeError(f"cinematic director returned an invalid scene at index {i + 1}")
        cleaned.append({
            "index": i + 1,
            "visual": str(item.get("visual") or sentences[i]).strip(),
            "beat": str(item.get("beat") or sentences[i]).strip(),
            "shot": str(item.get("shot") or "medium").strip().lower(),
            "transition": str(item.get("transition") or "cut").strip().lower(),
            "energy": str(item.get("energy") or "curious").strip().lower(),
        })
    bible = result.get("visual_bible")
    summary = str(result.get("story_summary") or "")
    if not isinstance(bible, dict) or not bible:
        fallback = analyze_story(
            sentences, image_style=image_style, provider=provider, model=model, hf_token=hf_token
        )
        bible = fallback.get("visual_bible", {})
        summary = summary or str(fallback.get("story_summary") or "")
    else:
        # The director names its keys differently from the rest of the pipeline; map them so continuity
        # (subjects, locations, rules) actually reaches every Runway prompt.
        bible = dict(bible)
        for source, target in (("subjects", "recurring_subjects"), ("locations", "recurring_locations"),
                               ("continuity", "continuity_rules"), ("palette", "color_palette")):
            if bible.get(source) and not bible.get(target):
                bible[target] = bible[source]
    storyboard = {"story_summary": summary, "visual_bible": bible}
    return {"storyboard": storyboard, "scenes": cleaned}

def write_visual_prompts(
    sentences: list[str],
    *,
    provider: str = "pollinations",
    model: str = "openai",
    hf_token: str | None = None,
    batch_size: int = 8,
    attempts: int = 3,
    story_context: dict[str, object] | None = None,
) -> list[str]:
    """Turn narration lines into concrete, text-free scene prompts.

    Long videos have dozens of scenes, and models rarely return a long JSON array
    with exactly the right length. Requests are therefore made in small batches;
    a batch that still fails after retrying falls back to its narration lines
    instead of discarding every prompt.
    """
    # Keep this lower-level helper compatible for callers that only want prompt
    # batches. The full-story path is explicit through write_storyboard().
    context = story_context or {
        "story_summary": "",
        "visual_bible": {},
    }
    results: list[str] = []
    previous = ""
    for offset in range(0, len(sentences), batch_size):
        batch = sentences[offset : offset + batch_size]
        prompts: list[str] | None = None
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                prompts = _visual_prompt_batch(
                    batch, previous, context, provider, model, hf_token
                )
                break
            except (RuntimeError, OnlineAIError) as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(4 * attempt)
        if prompts is None:
            LOGGER.warning(
                "Scene descriptions %d-%d failed (%s); using narration text for them.",
                offset + 1,
                offset + len(batch),
                last_error,
            )
            prompts = list(batch)
        else:
            previous = prompts[-1]
        results.extend(prompts)
        time.sleep(1.5)
    return results


def _visual_prompt_batch(
    batch: list[str],
    previous: str,
    story_context: dict[str, object],
    provider: str,
    model: str,
    hf_token: str | None,
) -> list[str]:
    numbered = "\n".join(f"{i}. {sentence}" for i, sentence in enumerate(batch, 1))
    continuity = (
        f"The previous scene was: {previous}\nKeep the same documentary-film look. "
        if previous
        else ""
    )
    bible = json.dumps(story_context, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        "You are the visual director of a premium faceless documentary. The narration was analyzed as one "
        "complete story before this request. For each numbered narration scene, "
        "write ONE image prompt of 18 to 32 words describing a concrete, filmable photorealistic scene: "
        "subject, setting, time of day, lighting, lens and camera angle. Vary wide establishing shots, "
        "medium action shots, over-the-shoulder views, macro details and low angles. People should look natural "
        "and candid, never like stock-photo models. Never include text, letters, logos or captions in the image. "
        "Keep recurring subjects, locations, weather, season, color palette, and period consistent with the "
        "visual bible. Do not replace a recurring subject with a random new person or location. "
        "Keep a coherent documentary-film style across the sequence. "
        f"VISUAL BIBLE:\n{bible}\n"
        f"{continuity}"
        f"Return ONLY a JSON array of exactly {len(batch)} strings, in order.\n\n{numbered}"
    )
    raw = generate_text(prompt, provider=provider, model=model, hf_token=hf_token)
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        raise RuntimeError("visual prompt model did not return a JSON array")
    try:
        prompts = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("visual prompt model returned invalid JSON") from exc
    if not isinstance(prompts, list) or len(prompts) != len(batch):
        raise RuntimeError("visual prompt model returned the wrong number of prompts")
    return [str(item).strip() or batch[i] for i, item in enumerate(prompts)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a narration script with Groq.")
    parser.add_argument("topic")
    parser.add_argument("--output", type=Path, default=Path("script.txt"))
    parser.add_argument("--provider", choices=["pollinations", "huggingface", "groq"], default="pollinations")
    parser.add_argument("--model", default="openai")
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.seconds < 10:
        parser.error("--seconds must be at least 10")
    try:
        text = write_script(
            args.topic,
            provider=args.provider,
            model=args.model,
            seconds=args.seconds,
            hf_token=args.hf_token,
        )
        args.output.write_text(text + "\n", encoding="utf-8")
    except RuntimeError as exc:
        parser.exit(1, f"error: {exc}\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()