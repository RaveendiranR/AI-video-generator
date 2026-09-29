/** Small typed helpers around the DOM. */
/** Find an element by id and check its type once, so the rest of the code never needs casts or null checks. */
export function byId(id, type) {
    const el = document.getElementById(id);
    if (!(el instanceof type)) {
        throw new Error(`The page is missing #${id} (expected ${type.name}).`);
    }
    return el;
}
export function all(selector) {
    return Array.from(document.querySelectorAll(selector));
}
export function setMsg(el, text, kind = "") {
    el.className = kind ? `msg ${kind}` : "msg";
    el.textContent = text;
}
export function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
export function debounce(fn, ms) {
    let timer;
    return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), ms);
    };
}
/** Narrow a string from the page or from storage to one of a fixed set of values. */
export function pick(value, allowed, fallback) {
    return allowed.find((item) => item === value) ?? fallback;
}
export function downloadText(filename, text, mime) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: mime }));
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
}
/** 75 -> "1m 15s" */
export function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.round(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    return minutes ? `${minutes}m ${String(seconds % 60).padStart(2, "0")}s` : `${seconds}s`;
}
/** Read a small text file chosen or dropped by the person. */
export async function readTextFile(file, maxBytes = 2_000_000) {
    if (file.size > maxBytes) {
        throw new Error(`${file.name} is too large (limit ${Math.round(maxBytes / 1_000_000)} MB).`);
    }
    return file.text();
}
