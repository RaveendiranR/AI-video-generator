# Faceless Video Maker

Portable, high-quality faceless YouTube video automation for Windows, macOS, and Linux.

Two ways to make videos: **photo videos** with AI images and slow zoom/pan (below) and **chart & diagram videos**: animated
motion-graphics explainers (`faceless-motion`). Both are available from the same web page (see next section) and from the command line.

The project turns a topic into a complete video:

1. Finds a current topic from Google Trends RSS, or accepts your topic.
2. Writes a retention-focused narration with an online model.
3. Generates photorealistic scene images with the Pollinations image endpoint, using selectable models and a compatibility fallback.
4. Optionally turns each scene into a premium cinematic moving shot with Runway Gen-4.5 image-to-video, using story continuity and varied camera direction.
5. Creates narration with either:
   - **Kokoro-82M on Hugging Face** — open model, deep/natural voices, free inference with a free HF token.
   - **edge-tts** — no token required, convenient fallback.
6. Adds captions, high-quality H.264 video, loudness-normalized voice, and background music.
7. Uploads to YouTube using the official OAuth flow.
8. Supports private, unlisted, public, and scheduled uploads.

No credentials are stored in the source archive. YouTube authentication happens in your browser on your own computer.



### 1.13.1 bug-fix release

- **Final-video check no longer rejects small valid videos.** A 50 KB minimum size failed simple videos (flat background, short scripts) after the whole render finished. It now checks that the file decodes and is about as long as expected.
- **Text-to-video really works.** Scenes with no image were sent to Runway's image-to-video endpoint, which needs an image; they now use text-to-video.
- **Runway errors are classified properly.** Auth or credit errors are detected from the HTTP status (not from digits in a message, so a request id like `1403` no longer aborts a render), and rejected prompts are not retried.
- **Claude director continuity reaches Runway.** The director's `subjects`/`locations`/`continuity` keys are mapped to the ones the prompt builder reads; before, continuity was silently dropped. The redundant second Claude request is also gone.
- **Storyboard cache fixes.** Scenes that fell back to raw narration are retried next run again; the cache is separate for Creator Pro runs; and the script is no longer sent to an AI service when nothing uses the prompts (AI images off, local motion).
- **Clearer Claude errors.** Failures say "Claude" instead of "Hugging Face", a bad key stops after one try, and long stories no longer get truncated (higher output limit and timeout).

### What's new in 1.13 (Creator Pro)

- **AI Director.** Each narration beat gets its own shot (lens, framing, camera move, lighting, focus, mood). Movement, emotional detail, reveals and settings are recognised, including verb endings ("walks", "discovered"). The same shot is never used twice in a row, and the opening shot gets hook-focused direction.
- **Continuity.** Recurring subjects, locations and continuity rules from the story's visual bible go into every prompt, trimmed to fit Runway's prompt-length limit (900 characters) so the shot direction is never the part that gets cut.
- **Quality gate.** Every AI clip is checked (size, readable, at least one second) before it enters the edit. A bad clip is discarded and that scene falls back to local motion; a bad cached clip is regenerated.
- **Safer runs.** Setup problems (missing package, missing or rejected key, no credits) stop at once with a clear message; the web page refuses Creator Pro up front without `RUNWAYML_API_SECRET`.
- **Cheaper and smoother.** Clips are requested at the length the scene needs (2-10 s) instead of always 5 or 10, and shorter clips loop forward-then-backward with no visible jump.
- **Fixes:** consistent versions, clean `requirements.txt` (optional Runway client in `requirements-video.txt`), the web UI no longer leaks the render pipe, and `POLLINATIONS_API_KEY` is also used for text requests.

### Advanced cinematic AI video

The photo-video workflow now has an **AI video creation** selector in the web UI:

- **Local cinematic motion** keeps the free Ken Burns workflow.
- **Cinematic AI — Runway Gen-4.5** generates real moving shots from the AI scene image.
- Each scene receives a director-style shot instruction such as an establishing push-in, tracking shot, rack focus, over-the-shoulder shot, macro insert, or low-angle dolly.
- The prompt preserves recurring characters, wardrobe, location, lighting, and physical continuity from the story bible.
- The final FFmpeg stage still handles narration, captions, music ducking, normalization, and Shorts formatting.
- Set `RUNWAYML_API_SECRET` in your environment before using the cinematic mode.

Runway's current Gen-4.5 API supports image-to-video and text-to-video generation, including portrait `720:1280` and landscape `1280:720` outputs. The project uses image-to-video here because the generated scene image provides a visual anchor for recurring subjects. 

## Install

### macOS / Linux

```bash
sh install.sh
. .venv/bin/activate
```

### Windows

```bat
install.bat
.venv\Scripts\activate
```

The package includes a Python FFmpeg fallback through `imageio-ffmpeg`. If you already have FFmpeg installed, that executable is preferred.

## The web page: photo videos and chart & diagram videos

```bash
./run-ui.sh          # macOS / Linux      (Windows: run-ui.bat)   ->  http://127.0.0.1:8765
```

Paste or write a script (or have one written from a topic, or load it from a link / `.txt`), pick a
**Video style**, and click **Create video**.

| Video style | What you get |
| --- | --- |
| **Photo video** | Exactly as before: AI pictures with slow zoom/pan behind the spoken captions. Options: AI images, Zoom/pan motion. |
| **Chart & diagram video** | Animated big text, kinetic words, loop/step diagrams and growing charts, drawn on your computer. No image generation needed. |

Shared by both styles: format (vertical / horizontal), speed/quality, **voice**, background music,
ALL CAPS text and "continue the previous run". The voice list, the speech engine, the AI background
images and the zoom/pan motion are the same code as in 1.6 and were not changed.

Extra options for chart & diagram videos:

| Option | What it does |
| --- | --- |
| Scene planning: **Smart** | A text model reads your script and understands it: numbers and trends become charts, processes and lists become diagrams, one-word punchlines become big kinetic text. It must keep your words exactly (each part is checked word for word); a part it gets wrong is planned by the offline rules instead. Needs internet. |
| Scene planning: **Quick** | Offline rules, no internet. |
| Highlight colour / Label | Your brand colour and the small label shown on the scenes. |
| Speak the narration | On by default. Turn off for a silent (music-only) video. |
| **Plan scenes from script** | Optional. Shows a thumbnail of every scene before you spend time rendering. Skip it and the scenes are planned automatically when you click Create. |
| Edit the scene plan | Advanced: edit the JSON, click **Update preview**, then **Save plan** / **Load plan** to keep it. **Load example** shows a finished 5-scene demo. |

If you change the script after planning, the page asks you to plan again (or Clear) so that what is
spoken always matches the scenes you see.

Horizontal chart & diagram videos work, but the layouts are designed for vertical 9:16.

### Page internals (1.9): TypeScript front end

The page is now a small typed TypeScript app instead of a string inside `webui.py`.

| Where | What |
| --- | --- |
| `frontend/src/*.ts` | Source: `api.ts` (typed client for every server route), `options.ts`, `script.ts`, `scenes.ts`, `job.ts`, `storage.ts`, `main.ts` |
| `faceless_video_generator/web/` | `index.html`, `styles.css`, `favicon.svg` and the **compiled** `js/`, which is committed so running the page needs no Node.js |

To change the page: `cd frontend && npm install && npm run build` (or `npm run watch`; `npm run typecheck` only checks types).

What the page gained: remembers your script and options between visits; drag a `.txt` onto the script box; Ctrl+Enter to create;
click a scene thumbnail to enlarge it (its narration is shown under it); live JSON check while editing a scene plan; elapsed time,
percentage in the browser tab title and a visible "lost contact with the server" notice; copy-log button; keyboard/screen-reader
support (real labels, live status, progress bar semantics, dark mode and reduced-motion respected).
The server now serves the page with a Content-Security-Policy and refuses requests whose Host header is not this computer.

## Motion-graphics videos (command line, since 1.7)

Besides photo slideshows, the project can now make **animated explainer videos** made of
kinetic typography, loop diagrams and charts: no image-generation service, no API keys, no
rate limits. Every frame is drawn locally, so renders are free, deterministic and work offline.

```bash
# 1. The built-in 5-scene demo (20 s, 1080x1920): hook, kinetic word, loop diagram, chart, outro
faceless-motion --demo -o demo.mp4

# 2. Turn any narration script into scenes (offline, no model needed)
faceless-motion --script script.txt --tag "DISCIPLINE" -o video.mp4

# 2b. Same, but a text model reads the script and picks the visual for each part (falls back to offline)
faceless-motion --script script.txt --ai-plan --narrate -o video.mp4

# 3. Let an online text model design the scenes for a topic
faceless-motion --topic "Why compound interest beats talent" --seconds 45 -o video.mp4

# 4. Full control: edit the JSON spec yourself and re-render
faceless-motion --demo --dry-run --save-spec my-video.json
faceless-motion --spec my-video.json -o video.mp4
```

Useful options:

| Option | What it does |
| --- | --- |
| `--ai-plan` | With `--script`: the AI understands the script and chooses a chart, diagram or typography scene per part. Your narration is verified word for word. |
| `--no-caps` | Keep your original capitalisation (now also honoured when planning from `--script`). |
| `--preview DIR` | Writes one PNG per scene and stops: the fastest way to check a design. |
| `--dry-run` | Prints the scene plan and timings. |
| `--accent "#3366FF"` | Recolours everything with your brand colour. |
| `--font my.ttf` | Uses your own font (default: bundled Poppins Bold/Medium). |
| `--narrate` | Speaks each scene's `narration` (edge-tts or Kokoro via `--tts-provider huggingface`); scenes stretch to fit the voice. |
| `--music file.mp3` / `--auto-music` | Background music, ducked under narration. |
| `--width/--height/--fps` | Output size. Portrait 9:16 is the design target. |

The video is silent unless you pass `--narrate` and/or music.

### Scene types

| `type` | Fields | Look |
| --- | --- | --- |
| `hook` | `tag`, `lines[]`, `accent` | Pill label, headline lines rising in one by one, last word in the accent colour. |
| `kinetic` | `small`, `big`, `spinner` | Small line and one huge word that pops in, with a spinner. |
| `steps` | `tag`, `nodes[]` (`label`, `sub`, `icon`, `title`), `loop` | Circular diagram: dashed placeholders fill in, arrows draw between nodes, the title follows the active step. 2-5 nodes. Icons: `spark cycle star check bolt dot`. |
| `chart` | `tag`, `title`, `curve` (`exp linear log s`), `x_labels[]`, `value`, `caption`, `show_curve` | A curve draws itself, then a glowing big number pops in. `show_curve: false` gives a plain statistic. |
| `outro` | `tag`, `lines[]`, `spinner` | Bold call-to-action on the accent colour. |

Every scene also takes `duration` (seconds), `theme` (`light`, `dark`, `accent`) and an optional
`narration`. See `examples/habit-loops.json` for a complete spec. Validation errors name the scene and
field, for example `scene 3 (steps): 'nodes' must be a list of 2 to 5 items.`

The offline `--script` planner makes the first sentence the hook and the last the outro. It breaks
the rest at natural pauses, turns short comma lists ("exercise, proper meals, enough sleep") into a
diagram, turns sentences with a number into a big-stat scene, and uses a one-word punchline as a
kinetic scene. Use `--save-spec` to tweak the result by hand.

From Python:

```python
from pathlib import Path
from faceless_video_generator.media import require_binary
from faceless_video_generator.motion import DEMO_SPEC, normalize_spec, render_video

render_video(normalize_spec(DEMO_SPEC), Path("demo.mp4"), ffmpeg=require_binary("ffmpeg"))
```

## Fastest working render

This uses edge-tts, Pollinations images, automatic ambient music, and 1080x1920 output:

```bash
python -m faceless_video_generator --script script.txt --output output.mp4
```

Use a local royalty-free music track:

```bash
python -m faceless_video_generator --music music.mp3 --force
```

Disable music completely:

```bash
python -m faceless_video_generator --no-music --force
```

## Story-aware image creation

The image pipeline does not send one isolated narration sentence to the image
model anymore. Before creating scene prompts, it reads the narration as one
complete story and builds a cached visual bible containing:

- the story arc and recurring subjects
- recurring locations, objects, time period, and visual motifs
- a consistent color palette, lighting approach, and camera language
- continuity rules for anatomy, materials, scale, weather, and physical cause and effect

It then creates each scene prompt from that visual bible plus the local narration
moment. This keeps a recurring notebook, location, person, or object visually
consistent across the video while still varying the shot type. The generated
`work/visual_prompts.json` file stores the story analysis and scene prompts so
resumed renders do not spend the analysis request again. Changing the image
style automatically invalidates that cache.

The default image model is Pollinations `flux`, with a realistic documentary
style. You can choose another available Pollinations model:

```bash
python -m faceless_video_generator \
  --script script.txt \
  --image-model flux \
  --image-style "photorealistic documentary photography, natural materials, motivated lighting, 35mm lens, no CGI, no illustration" \
  --force
```

For the most accurate workflow, write a complete script first and let the
story-aware planner create the scenes. Avoid `--no-smart-prompts`, because that
option intentionally skips story analysis and sends narration text directly to
the image generator.

## Open-model automatic creator

Create a video using Pollinations for script generation and Kokoro-82M for open-model voice:

```bash
export HF_TOKEN="hf_your_free_token"
faceless-create \
  --topic "The science of building better habits" \
  --seconds 600 \
  --tts-provider huggingface \
  --output output.mp4
```

`faceless-create` targets 600 seconds by default so it can produce a long-form video.
Use `--seconds 60` for a short video, or `--seconds 660` for a duration close to the
reference tutorial. The final duration follows the generated narration and voice speed;
this setting controls script length instead of looping a short clip.

For the current Pollinations `flux` endpoint, set `POLLINATIONS_API_KEY` in the
environment. The generator also keeps the older public endpoint as a fallback when
that service is available.

On Windows PowerShell:

```powershell
$env:HF_TOKEN="hf_your_free_token"
faceless-create --topic "The science of building better habits" --tts-provider huggingface
```

Use a live trend as the topic:

```bash
faceless-create --from-trends --region US --tts-provider huggingface
```

The open text-to-speech mode uses `hexgrad/Kokoro-82M` with the deeper `am_michael` voice by default. Change it with `--hf-tts-model` and choose another Kokoro voice such as `af_heart` or one supported by the selected model.

## Full-motion AI scenes

The default `ken-burns` mode moves still images locally. For real subject and object
motion, install the optional Runway client and provide `RUNWAYML_API_SECRET` through
your environment:

```bash
python -m pip install runwayml
export RUNWAYML_API_SECRET="your_secret"

faceless-create \
  --topic "The science of building better habits" \
  --seconds 60 \
  --video-provider runway \
  --video-model gen4.5 \
  --output motion-video.mp4
```

Runway creates a 5- or 10-second image-to-video clip for each scene, with prompts
that request physically plausible movement, consistent anatomy, gravity, momentum,
environmental motion, and cinematic camera movement. The clips are then synced to
the narration, captions, and music. A 10-minute video can require many paid
generation jobs, so test with `--seconds 60` first.

If you already have a script, generate a longer one first:

```bash
faceless-script "The science of building better habits" \
  --seconds 660 \
  --output script.txt
python -m faceless_video_generator \
  --script script.txt \
  --video-provider runway \
  --force
```

## YouTube upload

Install the optional Google client:

```bash
python -m pip install -r requirements-youtube.txt
```

### One-time Google setup

1. Create or select a Google Cloud project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth client of type **Desktop app**.
5. Download the JSON file as `client_secret.json` in this project folder.

Upload a rendered video:

```bash
faceless-publish output.mp4 \
  --title "The Science of Better Habits" \
  --description "A practical guide to building habits that last." \
  --tags habits,productivity,selfimprovement \
  --privacy private
```

The first run opens Google's consent page and saves a local `youtube-token.json`. Both credential files are ignored by Git.

Create and upload in one command:

```bash
faceless-create \
  --topic "The science of building better habits" \
  --tts-provider huggingface \
  --upload \
  --title "The Science of Better Habits" \
  --privacy private
```

Schedule a publish time in RFC 3339 format:

```bash
faceless-publish output.mp4 \
  --title "Scheduled Video" \
  --privacy private \
  --publish-at 2026-10-01T14:00:00Z
```

## Trend research

```bash
faceless-trends --region US --limit 10
```

Trend data is an opportunity signal, not a guarantee of virality. Review generated titles, scripts, and thumbnails before making a video public.

## Look and feel

- **Motion:** every generated image gets a slow zoom or pan so scenes do not feel frozen. Use `--no-motion` for faster renders.
- **Full motion:** use `--video-provider runway` to replace image pans with AI-generated motion clips. Without that flag, the generator remains local and free.
- **Captions:** large bold word chunks appear in the lower third with a pop-in animation. Use `--no-caps` for normal case.
- **Story-aware realistic images:** the full narration is analyzed into a visual bible before scene prompts are written. The default `flux` image model receives that bible plus real camera language, natural lighting, varied shot types, and text-free instructions. Set `--image-model` to another Pollinations model when available.
- **Fewer, longer scenes:** short sentences are merged into scenes of at least 14 words (`--min-scene-words 0` for one image per sentence). This means fewer hard cuts and far fewer image requests, so renders finish sooner on the rate-limited free tier.
- **Voice pace:** edge-tts speaks 8% faster by default. Override it with `--voice-rate=-5%`.
- **Cache correctness:** generated image names include a prompt fingerprint, so changing the style or visual prompt automatically creates fresh images.

## Quality controls

- Default output: 1080x1920, 30 FPS, H.264, CRF 18, AAC 192 kbps
- `--preset medium` balances quality and speed
- Voice loudness is normalized for clearer playback
- Music is automatically ducked under narration
- Captions are burned into the video
- `work/manifest.json` enables resumable scene rendering
- TTS and image assets are cached
- Final videos use `faststart` for better web playback

Example advanced render:

```bash
python -m faceless_video_generator \
  --script script.txt \
  --voice en-US-AndrewNeural \
  --width 1080 \
  --height 1920 \
  --fps 30 \
  --crf 18 \
  --preset medium \
  --music music.mp3 \
  --music-volume 0.06 \
  --force
```

For a faster render without online scene descriptions or motion:

```bash
python -m faceless_video_generator --no-smart-prompts --no-motion --force
```

## Commands

```bash
python -m faceless_video_generator --check
python -m faceless_video_generator --dry-run --no-music
python -m unittest discover -s tests -v
faceless-script "topic" --provider pollinations
faceless-trends --region US
faceless-publish output.mp4 --title "My Video"
```

## Online model notes

The no-key defaults use public services and may be rate-limited. For the strongest free open-model workflow, use a free Hugging Face token with Kokoro-82M. The package is provider-based so a service outage does not require rewriting the renderer.
## Creator Pro cinematic mode

The photo-video pipeline now includes a deterministic AI Director layer before Runway generation. It:

- analyzes each narration beat for shot intent;
- varies lens, framing, camera movement, focus and energy instead of cycling through generic zooms;
- carries the existing story visual bible into every shot;
- gives the opening scene a dedicated hook treatment;
- avoids repeating the same shot grammar back-to-back;
- validates generated motion clips with FFprobe before they enter the final edit;
- keeps resumable scene caching so failed or interrupted renders do not require starting over.

Runway Gen-4.5 currently supports image-to-video durations from 2–10 seconds and portrait `720:1280` output, which is used for Shorts-oriented rendering. See the official Runway API documentation for current model and pricing details.


## Creator Pro pipeline

Creator Pro can use Claude as the story-level director and Runway Gen-4.5 as the motion engine. Claude plans a compact visual bible and scene beats; the renderer converts those beats into provider-safe prompts. When an image is unavailable, Gen-4.5 may be called without `prompt_image` for text-to-video. Set `ANTHROPIC_API_KEY` and `RUNWAYML_API_SECRET` in `.env` to enable both.
