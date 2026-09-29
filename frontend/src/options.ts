import { all, pick } from "./dom.js";
import { els } from "./elements.js";
import { DIRECTOR_MODES, ORIENTATIONS, PLAN_MODES, QUALITIES, STYLES, VIDEO_MODES, type Options, type Style } from "./types.js";

const HEX = /^#[0-9a-f]{6}$/i;

const HINTS: Record<Style, string> = {
  photo: "AI-made pictures with a slow zoom/pan behind the spoken captions.",
  motion:
    "Animated charts, loop diagrams and big kinetic text drawn on your computer, so no image generation is needed. " +
    "The voice and music are the same as in photo videos. Vertical works best; horizontal is supported but the layouts are designed for vertical.",
};
const FAST_LABEL: Record<Style, string> = {
  photo: "Fast draft (720p, no zoom)",
  motion: "Fast draft (720p, 24 fps)",
};

/** Read every option from the page. */
export function readOptions(): Options {
  return {
    style: pick(els.style.value, STYLES, "photo"),
    orientation: pick(els.orient.value, ORIENTATIONS, "portrait"),
    quality: pick(els.quality.value, QUALITIES, "balanced"),
    voice: els.voice.value,
    video_mode: pick(els.videoMode.value, VIDEO_MODES, "local"),
    director: pick(els.director.value, DIRECTOR_MODES, "auto"),
    director_model: els.directorModel.value,
    plan: pick(els.planmode.value, PLAN_MODES, "smart"),
    accent: els.accent.value,
    tag: els.tag.value,
    ai_images: els.ai.checked,
    motion: els.motion.checked,
    narrate: els.narrate.checked,
    music: els.music.checked,
    caps: els.caps.checked,
    resume: els.resume.checked,
  };
}

function setSelect(select: HTMLSelectElement, value: unknown): void {
  if (typeof value === "string" && Array.from(select.options).some((option) => option.value === value)) {
    select.value = value;
  }
}

function setCheck(box: HTMLInputElement, value: unknown): void {
  if (typeof value === "boolean") box.checked = value;
}

/** Apply saved choices. Anything missing or invalid is ignored, so old or hand-edited storage cannot break the page. */
export function applyOptions(saved: Readonly<Record<string, unknown>>): void {
  setSelect(els.style, saved["style"]);
  setSelect(els.orient, saved["orientation"]);
  setSelect(els.quality, saved["quality"]);
  setSelect(els.voice, saved["voice"]);
  setSelect(els.videoMode, saved["video_mode"]);
  setSelect(els.director, saved["director"]);
  setSelect(els.directorModel, saved["director_model"]);
  setSelect(els.planmode, saved["plan"]);
  if (typeof saved["accent"] === "string" && HEX.test(saved["accent"])) els.accent.value = saved["accent"];
  if (typeof saved["tag"] === "string") els.tag.value = saved["tag"].slice(0, 40);
  setCheck(els.ai, saved["ai_images"]);
  setCheck(els.motion, saved["motion"]);
  setCheck(els.narrate, saved["narrate"]);
  setCheck(els.music, saved["music"]);
  setCheck(els.caps, saved["caps"]);
}

/** Show only the controls that belong to the chosen video style. */
export function applyStyle(): void {
  const style = pick(els.style.value, STYLES, "photo");
  const motion = style === "motion";
  for (const el of all(".motion")) el.hidden = !motion;
  for (const el of all(".photo")) el.hidden = motion;
  els.lg3.textContent = motion ? "4. Create" : "3. Create";
  els.hint.textContent = HINTS[style];
  const fast = els.quality.options[0];
  if (fast) fast.text = FAST_LABEL[style];
}

export function fillVoices(voices: readonly string[]): void {
  els.voice.replaceChildren(...voices.map((voice) => new Option(voice, voice)));
}
