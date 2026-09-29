import { getConfig } from "./api.js";
import { debounce, errorMessage } from "./dom.js";
import { els } from "./elements.js";
import { initJob, startJob } from "./job.js";
import { applyOptions, applyStyle, fillVoices } from "./options.js";
import { initScenes } from "./scenes.js";
import { initScript, setScript } from "./script.js";
import { loadSaved, save } from "./storage.js";

let noImageKey = false;
let noRunwayKey = false;
let noAnthropicKey = false;

/** AI pictures need a Pollinations key now; say so before a render is wasted on retries. */
function updateImageWarning(): void {
  const needs = noImageKey && els.style.value === "photo" && els.ai.checked;
  els.imgwarn.hidden = !needs;
  const cinematicNeedsKey =
    noRunwayKey && els.style.value === "photo" && els.videoMode.value === "cinematic";
  els.videoMode.title = cinematicNeedsKey
    ? "RUNWAYML_API_SECRET is not configured on this computer."
    : "";
  const needsClaude = els.videoMode.value === "cinematic" && els.director.value === "anthropic" && noAnthropicKey;
  els.director.title = needsClaude ? "ANTHROPIC_API_KEY is not configured; use Auto for fallback." : "";
  els.directorwarn.hidden = !(els.videoMode.value === "cinematic" && noAnthropicKey && els.director.value !== "none");
}

async function boot(): Promise<void> {
  try {
    const config = await getConfig();
    fillVoices(config.voices);
    els.accent.value = config.default_accent.toLowerCase();
    noImageKey = !config.image_key;
    noRunwayKey = !config.runway_key;
    noAnthropicKey = !config.anthropic_key;
  } catch (error) {
    els.banner.textContent = `Could not reach the local server: ${errorMessage(error)}`;
    els.banner.hidden = false;
  }

  const saved = loadSaved();
  applyOptions(saved.options);
  applyStyle();
  updateImageWarning();
  if (saved.script) setScript(saved.script);

  initScript(() => void startJob());
  initScenes();
  initJob();

  els.style.addEventListener("change", applyStyle);
  for (const control of [els.style, els.ai, els.videoMode, els.director]) control.addEventListener("change", updateImageWarning);
  const remember = debounce(save, 400);
  for (const control of [els.script, els.tag]) control.addEventListener("input", remember);
  for (const control of [
    els.style, els.orient, els.quality, els.voice, els.videoMode, els.director, els.directorModel, els.planmode, els.accent,
    els.ai, els.motion, els.narrate, els.music, els.caps,
  ]) {
    control.addEventListener("change", remember);
  }
}

void boot();
