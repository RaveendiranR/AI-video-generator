import type { AppConfig, PostRoutes, StatusResponse } from "./types.js";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function hasError(value: unknown): value is { error: string } {
  return typeof value === "object" && value !== null && typeof (value as { error?: unknown }).error === "string";
}

async function parse<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(`The local server sent an unexpected reply (${response.status}).`, response.status);
  }
  if (!response.ok) {
    throw new ApiError(hasError(body) ? body.error : `Request failed (${response.status}).`, response.status);
  }
  return body as T;
}

/** POST JSON to the local server. The extra header is what the server checks to reject requests from other sites. */
export async function post<P extends keyof PostRoutes>(
  path: P,
  body: PostRoutes[P]["req"] = {} as PostRoutes[P]["req"],
): Promise<PostRoutes[P]["res"]> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "faceless-ui" },
    body: JSON.stringify(body),
  });
  return parse<PostRoutes[P]["res"]>(response);
}

export const getStatus = async (): Promise<StatusResponse> => parse(await fetch("/api/status", { cache: "no-store" }));
export const getConfig = async (): Promise<AppConfig> => parse(await fetch("/api/config", { cache: "no-store" }));
