import { post } from "./api.js";
import { readTextFile } from "./dom.js";
import { els } from "./elements.js";
import { runTask } from "./tasks.js";
const WORDS_PER_SECOND = 2.6; // typical speaking pace of the voices
/** Replace the script and let everything that watches it (word count, plan check, autosave) know. */
export function setScript(text) {
    els.script.value = text;
    els.script.dispatchEvent(new Event("input", { bubbles: true }));
}
function updateCount() {
    const words = els.script.value.trim().split(/\s+/).filter(Boolean).length;
    els.count.textContent = words ? `${words} words, about ${Math.round(words / WORDS_PER_SECOND)} seconds when spoken.` : "";
}
async function importFile(file) {
    await runTask([els.load, els.write], els.smsg, `Reading ${file.name}...`, async () => {
        setScript(await readTextFile(file));
        return `Loaded ${file.name}. Review and edit the script below.`;
    });
}
export function initScript(onCreate) {
    els.script.addEventListener("input", updateCount);
    els.write.addEventListener("click", () => runTask([els.write, els.load], els.smsg, "Writing script (long ones take a few minutes)...", async () => {
        const { text } = await post("/api/script", { topic: els.topic.value, seconds: Number(els.secs.value) || 60 });
        setScript(text);
        return "Done. Review and edit the script below.";
    }));
    els.load.addEventListener("click", () => runTask([els.load, els.write], els.smsg, "Loading link...", async () => {
        const { text } = await post("/api/fetch", { url: els.link.value });
        setScript(text);
        return "Done. Review and edit the script below.";
    }));
    els.file.addEventListener("change", () => {
        const file = els.file.files?.[0];
        els.file.value = "";
        if (file)
            void importFile(file);
    });
    // Drag a text file onto the script box.
    for (const type of ["dragenter", "dragover"]) {
        els.script.addEventListener(type, (event) => {
            if (event.dataTransfer?.types.includes("Files")) {
                event.preventDefault();
                els.script.classList.add("drop");
            }
        });
    }
    els.script.addEventListener("dragleave", () => els.script.classList.remove("drop"));
    els.script.addEventListener("drop", (event) => {
        els.script.classList.remove("drop");
        const file = event.dataTransfer?.files[0];
        if (file) {
            event.preventDefault();
            void importFile(file);
        }
    });
    // Ctrl/Cmd + Enter creates the video from anywhere in the script box.
    els.script.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onCreate();
        }
    });
    updateCount();
}
