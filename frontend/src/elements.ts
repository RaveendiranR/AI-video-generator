import { byId } from "./dom.js";

/** Every element the script touches, looked up and type-checked once at start-up. */
export const els = {
  banner: byId("banner", HTMLElement),

  // 1. Script
  topic: byId("topic", HTMLInputElement),
  secs: byId("secs", HTMLInputElement),
  write: byId("write", HTMLButtonElement),
  link: byId("link", HTMLInputElement),
  load: byId("load", HTMLButtonElement),
  file: byId("file", HTMLInputElement),
  script: byId("script", HTMLTextAreaElement),
  smsg: byId("smsg", HTMLElement),
  count: byId("count", HTMLElement),

  // 2. Options
  style: byId("style", HTMLSelectElement),
  hint: byId("hint", HTMLElement),
  imgwarn: byId("imgwarn", HTMLElement),
  orient: byId("orient", HTMLSelectElement),
  quality: byId("quality", HTMLSelectElement),
  voice: byId("voice", HTMLSelectElement),
  videoMode: byId("video_mode", HTMLSelectElement),
  director: byId("director", HTMLSelectElement),
  directorModel: byId("director_model", HTMLSelectElement),
  directorwarn: byId("directorwarn", HTMLElement),
  planmode: byId("planmode", HTMLSelectElement),
  accent: byId("accent", HTMLInputElement),
  tag: byId("tag", HTMLInputElement),
  ai: byId("ai", HTMLInputElement),
  motion: byId("motion", HTMLInputElement),
  narrate: byId("narrate", HTMLInputElement),
  music: byId("music", HTMLInputElement),
  caps: byId("caps", HTMLInputElement),
  resume: byId("resume", HTMLInputElement),

  // 3. Scenes
  scenes: byId("scenes", HTMLFieldSetElement),
  planBtn: byId("plan_btn", HTMLButtonElement),
  demo: byId("demo", HTMLButtonElement),
  reprev: byId("reprev", HTMLButtonElement),
  saveplan: byId("saveplan", HTMLButtonElement),
  clear: byId("clear", HTMLButtonElement),
  planfile: byId("planfile", HTMLInputElement),
  pmsg: byId("pmsg", HTMLElement),
  stale: byId("stale", HTMLElement),
  grid: byId("grid", HTMLElement),
  spec: byId("spec", HTMLTextAreaElement),
  specerr: byId("specerr", HTMLElement),
  lightbox: byId("lightbox", HTMLDialogElement),
  lightimg: byId("lightimg", HTMLImageElement),
  lightcap: byId("lightcap", HTMLElement),
  lightclose: byId("lightclose", HTMLButtonElement),

  // Create
  lg3: byId("lg3", HTMLElement),
  go: byId("go", HTMLButtonElement),
  stop: byId("stop", HTMLButtonElement),
  state: byId("state", HTMLElement),
  bar: byId("bar", HTMLElement),
  fill: byId("fill", HTMLElement),
  logbox: byId("logbox", HTMLDetailsElement),
  log: byId("log", HTMLElement),
  copylog: byId("copylog", HTMLButtonElement),
  result: byId("result", HTMLElement),
  vid: byId("vid", HTMLVideoElement),
} as const;
