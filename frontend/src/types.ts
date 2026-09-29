/** Shapes shared between the page and the Python server (see faceless_video_generator/webui.py). */

export type Style = "photo" | "motion";
export type Orientation = "portrait" | "landscape";
export type Quality = "fast" | "balanced" | "best";
export type PlanMode = "smart" | "offline";
export type VideoMode = "local" | "cinematic";
export type DirectorMode = "auto" | "anthropic" | "pollinations" | "none";
export type JobStatus = "idle" | "running" | "done" | "error" | "cancelled";

export const STYLES = ["photo", "motion"] as const satisfies readonly Style[];
export const ORIENTATIONS = ["portrait", "landscape"] as const satisfies readonly Orientation[];
export const QUALITIES = ["fast", "balanced", "best"] as const satisfies readonly Quality[];
export const PLAN_MODES = ["smart", "offline"] as const satisfies readonly PlanMode[];
export const VIDEO_MODES = ["local", "cinematic"] as const satisfies readonly VideoMode[];
export const DIRECTOR_MODES = ["auto", "anthropic", "pollinations", "none"] as const satisfies readonly DirectorMode[];

/** Every choice on the Options panel. */
export interface Options {
  style: Style;
  orientation: Orientation;
  quality: Quality;
  voice: string;
  video_mode: VideoMode;
  director: DirectorMode;
  director_model: string;
  plan: PlanMode;
  accent: string;
  tag: string;
  ai_images: boolean;
  motion: boolean;
  narrate: boolean;
  music: boolean;
  caps: boolean;
  resume: boolean;
}

export interface SceneSpec {
  type: string;
  duration: number;
  narration: string;
  [key: string]: unknown;
}

export interface PlanSpec {
  style: { accent: string; [key: string]: unknown };
  scenes: SceneSpec[];
  [key: string]: unknown;
}

export interface PreviewScene {
  type: string;
  duration: number;
  image: string; // data: URL
}

export interface AppConfig {
  voices: string[];
  default_accent: string;
  /** True when POLLINATIONS_API_KEY is set on the server. */
  image_key: boolean;
  /** True when RUNWAYML_API_SECRET is set on the server. */
  runway_key: boolean;
  /** True when ANTHROPIC_API_KEY is set on the server. */
  anthropic_key: boolean;
}

export interface StatusResponse {
  status: JobStatus;
  log: string[];
  total: number;
  done: number;
  pct: number | null;
  phase: string;
  elapsed: number;
  video: boolean;
}

export interface StartRequest extends Options {
  script: string;
  spec: string;
}

export interface PlanRequest {
  script: string;
  plan: PlanMode;
  tag: string;
  accent: string;
  caps: boolean;
}

export interface PreviewRequest {
  spec: string;
  orientation: Orientation;
  caps: boolean;
  /** Empty string keeps the accent stored in the plan. */
  accent: string;
}

/** POST routes: request body and JSON reply for each. */
export interface PostRoutes {
  "/api/start": { req: StartRequest; res: { ok: true } };
  "/api/cancel": { req: Record<string, never>; res: { ok: true } };
  "/api/fetch": { req: { url: string }; res: { text: string } };
  "/api/script": { req: { topic: string; seconds: number }; res: { text: string } };
  "/api/plan": { req: PlanRequest; res: { spec: PlanSpec; warnings: string[] } };
  "/api/preview": { req: PreviewRequest; res: { spec: PlanSpec; scenes: PreviewScene[] } };
  "/api/demo": { req: Record<string, never>; res: { spec: PlanSpec; script: string } };
}
