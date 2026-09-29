import { readOptions } from "./options.js";
import { els } from "./elements.js";

const KEY = "faceless-ui:v2";

export interface Saved {
  options: Record<string, unknown>;
  script: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Restore what the person had last time. Storage can be blocked or corrupt, so every failure just means "start fresh". */
export function loadSaved(): Saved {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (isRecord(parsed)) {
      return {
        options: isRecord(parsed["options"]) ? parsed["options"] : {},
        script: typeof parsed["script"] === "string" ? parsed["script"] : "",
      };
    }
  } catch {
    /* ignore */
  }
  return { options: {}, script: "" };
}

export function save(): void {
  const { resume: _resume, ...options } = readOptions(); // "continue previous run" is deliberately not remembered
  try {
    localStorage.setItem(KEY, JSON.stringify({ options, script: els.script.value }));
  } catch {
    /* storage full or blocked: the page still works, it just will not remember */
  }
}
