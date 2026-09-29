export class ApiError extends Error {
    status;
    constructor(message, status) {
        super(message);
        this.status = status;
        this.name = "ApiError";
    }
}
function hasError(value) {
    return typeof value === "object" && value !== null && typeof value.error === "string";
}
async function parse(response) {
    let body;
    try {
        body = await response.json();
    }
    catch {
        throw new ApiError(`The local server sent an unexpected reply (${response.status}).`, response.status);
    }
    if (!response.ok) {
        throw new ApiError(hasError(body) ? body.error : `Request failed (${response.status}).`, response.status);
    }
    return body;
}
/** POST JSON to the local server. The extra header is what the server checks to reject requests from other sites. */
export async function post(path, body = {}) {
    const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "faceless-ui" },
        body: JSON.stringify(body),
    });
    return parse(response);
}
export const getStatus = async () => parse(await fetch("/api/status", { cache: "no-store" }));
export const getConfig = async () => parse(await fetch("/api/config", { cache: "no-store" }));
