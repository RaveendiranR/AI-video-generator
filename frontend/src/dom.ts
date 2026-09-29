/** Small typed helpers around the DOM. */

/** Find an element by id and check its type once, so the rest of the code never needs casts or null checks. */
export function byId<T extends HTMLElement>(id: string, type: new () => T): T {
  const el = document.getElementById(id);
  if (!(el instanceof type)) {
    throw new Error(`The page is missing #${id} (expected ${type.name}).`);
  }
  return el;
}

export function all<T extends HTMLElement>(selector: string): T[] {
  return Array.from(document.querySelectorAll<T>(selector));
}

export type MsgKind = "" | "ok" | "warn" | "err";

export function setMsg(el: HTMLElement, text: string, kind: MsgKind = ""): void {
  el.className = kind ? `msg ${kind}` : "msg";
  el.textContent = text;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let timer: number | undefined;
  return (...args: A) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), ms);
  };
}

/** Narrow a string from the page or from storage to one of a fixed set of values. */
export function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.find((item) => item === value) ?? fallback;
}

export function downloadText(filename: string, text: string, mime: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: mime }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

/** 75 -> "1m 15s" */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${String(seconds % 60).padStart(2, "0")}s` : `${seconds}s`;
}

/** Read a small text file chosen or dropped by the person. */
export async function readTextFile(file: File, maxBytes = 2_000_000): Promise<string> {
  if (file.size > maxBytes) {
    throw new Error(`${file.name} is too large (limit ${Math.round(maxBytes / 1_000_000)} MB).`);
  }
  return file.text();
}
