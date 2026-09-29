import { errorMessage, setMsg } from "./dom.js";
/**
 * Run one button's action: disable the given buttons meanwhile, show a "working" message,
 * then show the result (or the error) in the same message line.
 */
export async function runTask(buttons, msg, pending, action) {
    const wasDisabled = buttons.map((button) => button.disabled);
    buttons.forEach((button) => (button.disabled = true));
    setMsg(msg, pending);
    try {
        setMsg(msg, (await action()) ?? "");
    }
    catch (error) {
        setMsg(msg, errorMessage(error), "err");
    }
    finally {
        buttons.forEach((button, i) => (button.disabled = wasDisabled[i] ?? false));
    }
}
