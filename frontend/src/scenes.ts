import { post } from "./api.js";
import { all, debounce, downloadText, errorMessage, readTextFile, setMsg } from "./dom.js";
import { els } from "./elements.js";
import { readOptions } from "./options.js";
import { setScript } from "./script.js";
import { runTask } from "./tasks.js";
import type { PlanSpec, PreviewScene } from "./types.js";

/** What the plan was made from. If the script, label or caps setting changes, the plan no longer matches what will be spoken. */
let plannedFrom: string | null = null;

const planKey = (): string => JSON.stringify([els.script.value.trim(), els.tag.value.trim(), els.caps.checked]);
const sceneButtons = (): HTMLButtonElement[] => all<HTMLButtonElement>("#scenes button");

export const currentSpec = (): string => els.spec.value.trim();

/** True when there is no plan, or the plan was made from the script and label as they are now. */
export const isPlanCurrent = (): boolean => !currentSpec() || plannedFrom === planKey();

function markStale(): void {
  els.stale.hidden = !(currentSpec() && plannedFrom !== null && plannedFrom !== planKey());
}

function markCurrent(): void {
  plannedFrom = planKey();
  els.stale.hidden = true;
}

function narrationOf(spec: PlanSpec, index: number): string {
  return spec.scenes[index]?.narration ?? "";
}

function renderScenes(spec: PlanSpec, scenes: readonly PreviewScene[]): void {
  els.spec.value = JSON.stringify(spec, null, 2);
  validateSpecText();
  const figures = scenes.map((scene, i) => {
    const figure = document.createElement("figure");
    const button = document.createElement("button");
    const image = new Image();
    const caption = document.createElement("figcaption");
    const label = document.createElement("span");
    const words = document.createElement("span");
    const narration = narrationOf(spec, i);

    button.type = "button";
    button.className = "thumb";
    button.title = "Click to enlarge";
    image.src = scene.image;
    image.alt = `Scene ${i + 1}: ${scene.type}`;
    button.append(image);
    button.addEventListener("click", () => openLightbox(scene, i, narration));

    label.textContent = `${i + 1}. ${scene.type} · ${scene.duration.toFixed(1)}s`;
    words.textContent = narration;
    words.title = narration;
    caption.append(label, words);
    figure.append(button, caption);
    return figure;
  });
  els.grid.replaceChildren(...figures);
}

function openLightbox(scene: PreviewScene, index: number, narration: string): void {
  els.lightimg.src = scene.image;
  els.lightimg.alt = `Scene ${index + 1}: ${scene.type}`;
  els.lightcap.textContent = `${index + 1}. ${scene.type} · ${scene.duration.toFixed(1)}s${narration ? ` — ${narration}` : ""}`;
  els.lightbox.showModal();
}

/** Ask the server to check the (possibly hand-edited) plan and draw every scene. */
async function preview(keepPlanAccent: boolean): Promise<{ spec: PlanSpec; scenes: PreviewScene[] }> {
  const options = readOptions();
  const result = await post("/api/preview", {
    spec: els.spec.value,
    orientation: options.orientation,
    caps: options.caps,
    accent: keepPlanAccent ? "" : options.accent,
  });
  renderScenes(result.spec, result.scenes);
  return result;
}

/** Make the script box match the words the plan will speak, and take over the plan's colour. */
function adopt(spec: PlanSpec): void {
  setScript(spec.scenes.map((scene) => scene.narration).filter(Boolean).join(" "));
  if (/^#[0-9a-f]{6}$/i.test(spec.style.accent)) els.accent.value = spec.style.accent.toLowerCase();
  markCurrent();
}

/** Tell the person right away if the JSON they are editing is broken, instead of after a round trip. */
function validateSpecText(): void {
  const text = els.spec.value.trim();
  if (!text) return setMsg(els.specerr, "");
  try {
    JSON.parse(text);
    setMsg(els.specerr, "");
  } catch (error) {
    setMsg(els.specerr, `Not valid JSON yet: ${errorMessage(error)}`, "warn");
  }
}

function clearPlan(): void {
  els.spec.value = "";
  els.grid.replaceChildren();
  plannedFrom = null;
  els.stale.hidden = true;
  setMsg(els.specerr, "");
  setMsg(els.pmsg, "");
}

const run = (pending: string, action: () => Promise<string | void>): Promise<void> =>
  runTask(sceneButtons(), els.pmsg, pending, action);

export function initScenes(): void {
  for (const control of [els.script, els.tag]) control.addEventListener("input", markStale);
  els.caps.addEventListener("change", markStale);
  els.spec.addEventListener("input", debounce(validateSpecText, 250));

  els.planBtn.addEventListener("click", () => {
    const options = readOptions();
    const smart = options.plan === "smart";
    void run(smart ? "Planning scenes: the AI is reading your script (long scripts take a minute or two)..." : "Planning scenes...", async () => {
      const plan = await post("/api/plan", {
        script: els.script.value, plan: options.plan, tag: options.tag, accent: options.accent, caps: options.caps,
      });
      els.spec.value = JSON.stringify(plan.spec);
      const result = await preview(false);
      markCurrent();
      return `Planned ${result.scenes.length} scenes. ${plan.warnings.join(" ")}`.trim();
    });
  });

  els.demo.addEventListener("click", () =>
    void run("Loading the example...", async () => {
      const demo = await post("/api/demo");
      els.spec.value = JSON.stringify(demo.spec);
      const result = await preview(true);
      adopt(result.spec);
      return `Loaded the ${result.scenes.length}-scene example (a habit loop). Change the voice/format above, then click Create.`;
    }),
  );

  els.reprev.addEventListener("click", () =>
    void run("Checking and drawing the scenes...", async () => {
      const result = await preview(false);
      return `Scene plan is valid: ${result.scenes.length} scenes.`;
    }),
  );

  els.planfile.addEventListener("change", () => {
    const file = els.planfile.files?.[0];
    els.planfile.value = "";
    if (!file) return;
    void run("Reading the plan...", async () => {
      els.spec.value = await readTextFile(file);
      const result = await preview(true);
      adopt(result.spec);
      return `Loaded ${result.scenes.length} scenes from ${file.name}. The script box now shows the words the plan will speak.`;
    });
  });

  els.saveplan.addEventListener("click", () => {
    if (!currentSpec()) return setMsg(els.pmsg, "Nothing to save yet. Plan the scenes first.", "err");
    downloadText("scene-plan.json", els.spec.value, "application/json");
  });

  els.clear.addEventListener("click", clearPlan);
  els.accent.addEventListener("change", () => {
    if (currentSpec()) els.reprev.click();
  });

  els.lightclose.addEventListener("click", () => els.lightbox.close());
  els.lightbox.addEventListener("click", (event) => {
    if (event.target === els.lightbox) els.lightbox.close(); // click on the dimmed backdrop
  });
}
