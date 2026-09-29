import { getStatus, post } from "./api.js";
import { errorMessage, formatDuration, setMsg } from "./dom.js";
import { els } from "./elements.js";
import { readOptions } from "./options.js";
import { currentSpec, isPlanCurrent } from "./scenes.js";
const RUNNING_MS = 1500;
const IDLE_MS = 4000;
const BACKGROUND_MS = 5000; // hidden tab: no need to poll quickly
const BASE_TITLE = "Faceless Video Maker";
const LABELS = {
    idle: "Ready.",
    running: "Creating video...",
    done: "Finished!",
    error: "Something went wrong. See the log below.",
    cancelled: "Cancelled.",
};
let timer;
let failures = 0;
let lastStatus = "idle";
let lastLog = "";
/** Percentage shown in the bar: motion videos report one, photo videos count scenes. */
function progress(status) {
    if (status.status === "done")
        return 100;
    if (status.pct !== null)
        return status.pct;
    if (status.total)
        return Math.min(100, Math.round((100 * status.done) / status.total));
    return status.status === "running" ? 3 : 0;
}
function describe(status, pct) {
    let text = LABELS[status.status];
    if (status.status === "running") {
        if (status.pct !== null && status.phase)
            text += ` ${status.phase} (${pct}%)`;
        else if (status.total)
            text += ` Scene ${status.done} of ${status.total} (${pct}%)`;
    }
    if (status.elapsed > 0 && status.status !== "idle")
        text += ` · ${formatDuration(status.elapsed)}`;
    return text;
}
function renderLog(lines) {
    const text = lines.join("\n");
    if (text === lastLog)
        return; // do not disturb scrolling or text selection when nothing changed
    const atEnd = els.log.scrollTop + els.log.clientHeight >= els.log.scrollHeight - 20;
    els.log.textContent = text;
    lastLog = text;
    if (atEnd)
        els.log.scrollTop = els.log.scrollHeight;
}
function render(status) {
    const running = status.status === "running";
    const pct = progress(status);
    els.go.disabled = running;
    els.stop.disabled = !running;
    els.fill.style.width = `${pct}%`;
    els.bar.setAttribute("aria-valuenow", String(pct));
    els.bar.classList.toggle("busy", running);
    setMsg(els.state, describe(status, pct), status.status === "error" ? "err" : status.status === "done" ? "ok" : "");
    renderLog(status.log);
    if (status.status === "error" && lastStatus !== "error")
        els.logbox.open = true;
    document.title = running ? `${pct}% · ${BASE_TITLE}` : status.status === "done" ? `Done · ${BASE_TITLE}` : BASE_TITLE;
    if (status.video && els.result.hidden) {
        els.vid.src = `/output.mp4?t=${Date.now()}`; // cache-buster so a new render is not replaced by the old file
        els.result.hidden = false;
    }
    lastStatus = status.status;
}
async function tick() {
    let delay = IDLE_MS;
    try {
        const status = await getStatus();
        failures = 0;
        els.banner.hidden = true;
        render(status);
        delay = status.status === "running" ? RUNNING_MS : IDLE_MS;
    }
    catch {
        failures += 1;
        els.banner.textContent = "Lost contact with the local server. Is the terminal window still running? Retrying...";
        els.banner.hidden = false;
        delay = Math.min(10_000, RUNNING_MS * (failures + 1));
    }
    timer = window.setTimeout(() => void tick(), document.hidden ? Math.max(delay, BACKGROUND_MS) : delay);
}
/** Check the server now instead of waiting for the next scheduled poll. */
function pollNow() {
    window.clearTimeout(timer);
    void tick();
}
export async function startJob() {
    if (els.go.disabled)
        return;
    setMsg(els.state, "");
    try {
        const options = readOptions();
        const motion = options.style === "motion";
        const spec = motion ? currentSpec() : "";
        if (spec && !isPlanCurrent()) {
            throw new Error('The script or label changed after the scenes were planned. Click "Plan scenes from script" again, or Clear the scenes to have them planned automatically.');
        }
        els.go.disabled = true;
        await post("/api/start", { ...options, script: els.script.value, spec });
        els.result.hidden = true;
        lastLog = "";
        pollNow();
    }
    catch (error) {
        els.go.disabled = false;
        setMsg(els.state, errorMessage(error), "err");
    }
}
export function initJob() {
    els.go.addEventListener("click", () => void startJob());
    els.stop.addEventListener("click", () => {
        els.stop.disabled = true;
        void post("/api/cancel").then(pollNow, (error) => setMsg(els.state, errorMessage(error), "err"));
    });
    els.copylog.addEventListener("click", () => {
        const done = (text) => {
            els.copylog.textContent = text;
            window.setTimeout(() => (els.copylog.textContent = "Copy log"), 1500);
        };
        navigator.clipboard.writeText(els.log.textContent ?? "").then(() => done("Copied"), () => done("Copy failed"));
    });
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden)
            pollNow();
    });
    pollNow();
}
