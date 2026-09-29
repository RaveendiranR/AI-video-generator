from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Iterable

from .captions import build_ass
from .config import DEFAULT_IMAGE_EXTENSIONS, VideoConfig
from .director import ShotPlan, build_prompt, plan_shot
from .media import CommandError, concat_escape, probe_duration, require_binary, run_command
from .music import create_ambient_bed, download_music
from .online_ai import OnlineAIError, synthesize_huggingface
from .script_writer import clean_narration, plan_cinematic_storyboard, write_storyboard
from .video_generation import RunwayVideoProvider, VideoProviderError

LOGGER = logging.getLogger("faceless_video_generator")


class RenderError(RuntimeError):
    """Raised for a user-fixable render error."""


class VideoGenerator:
    def __init__(self, config: VideoConfig):
        self.config = config.resolve()
        self.config.validate()
        self.ffmpeg = require_binary("ffmpeg") if not self.config.dry_run else "ffmpeg"
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.config.ai_images_dir.mkdir(parents=True, exist_ok=True)
        self._visual_prompts: list[str] = []
        self._story_context: dict[str, object] = {}
        self._image_failures = 0  # scenes in a row whose image could not be made
        self._images_disabled = False
        self._previous_shot: ShotPlan | None = None
        self._director_scenes: list[dict[str, object]] = []

    def render(self) -> Path:
        script_text = self._read_script()
        sentences = group_sentences(split_sentences(script_text), self.config.min_scene_words)
        if not sentences:
            raise RenderError(f"Script is empty: {self.config.script}")
        if self.config.output.exists() and not self.config.force:
            raise RenderError(
                f"Output already exists: {self.config.output}. Use --force to replace it."
            )

        own_images = self._find_images(self.config.images_dir)
        manifest = self._load_manifest()
        script_hash = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
        config_dict = self.config.to_manifest_dict()
        self._visual_prompts = self._load_visual_prompts(sentences, script_hash)
        can_resume = (
            self.config.resume
            and manifest.get("script_hash") == script_hash
            and manifest.get("config") == config_dict
        )
        LOGGER.info(
            "Rendering %d scenes (%d local images, resume=%s)",
            len(sentences),
            len(own_images),
            can_resume,
        )

        scene_records: list[dict[str, object]] = []
        for index, sentence in enumerate(sentences):
            record = self._render_scene(
                index=index,
                sentence=sentence,
                own_images=own_images,
                previous=manifest.get("scenes", [])[index] if can_resume and index < len(manifest.get("scenes", [])) else None,
            )
            scene_records.append(record)
            self._write_manifest(script_hash, config_dict, scene_records)

        if self.config.dry_run:
            LOGGER.info("Dry run complete: no audio, images, or video were generated.")
            return self.config.output

        subtitle_path = self.config.work_dir / "captions.ass"
        subtitle_path.write_text(
            build_ass(
                scene_records,
                width=self.config.width,
                height=self.config.height,
                font_size=self.config.caption_font_size,
                margin_v=self.config.caption_margin,
                tail_padding=self.config.scene_padding,
                uppercase=self.config.caption_uppercase,
            ),
            encoding="utf-8",
        )
        concat_path = self.config.work_dir / "concat.txt"
        concat_path.write_text(
            "\n".join(f"file '{concat_escape(str(record['clip']))}'" for record in scene_records)
            + "\n",
            encoding="utf-8",
        )

        joined_path = self.config.work_dir / "joined.mp4"
        self._concat_clips(concat_path, joined_path)
        total_duration = sum(float(scene["duration"]) for scene in scene_records)
        music_path = self._prepare_music(total_duration)
        self._finalize_video(joined_path, subtitle_path, self.config.output, music_path)
        self._validate_final_video(self.config.output, expected_duration=total_duration)
        self._write_manifest(script_hash, config_dict, scene_records, completed=True)
        LOGGER.info("Done: %s", self.config.output)
        return self.config.output

    def _render_scene(
        self,
        *,
        index: int,
        sentence: str,
        own_images: list[Path],
        previous: dict[str, object] | None,
    ) -> dict[str, object]:
        wav_path = self.config.work_dir / f"scene-{index:03d}.wav"
        clip_path = self.config.work_dir / f"scene-{index:03d}.mp4"
        text_hash = hashlib.sha256(
            f"{self.config.tts_provider}\0{self.config.voice}\0{self.config.voice_rate}\0{sentence}".encode()
        ).hexdigest()[:16]
        expected_audio = self.config.work_dir / f"tts-{text_hash}.wav"

        if (
            previous
            and previous.get("sentence") == sentence
            and Path(str(previous.get("clip", ""))).exists()
            and Path(str(previous.get("audio", ""))).exists()
        ):
            LOGGER.info("[%d] Reusing completed scene", index + 1)
            return previous

        LOGGER.info("[%d] %s", index + 1, sentence[:100])
        if self.config.dry_run:
            image = self._select_image(index, sentence, own_images)
            estimated_duration = max(1.0, len(sentence.split()) / 2.5) + self.config.scene_padding
            LOGGER.info(
                "[%d] dry-run: image=%s estimated_duration=%.2fs",
                index + 1,
                image or "background",
                estimated_duration,
            )
            return {
                "index": index,
                "sentence": sentence,
                "audio": str(expected_audio),
                "image": str(image) if image else None,
                "clip": str(clip_path),
                "duration": round(estimated_duration, 3),
            }

        if expected_audio.exists():
            wav_path = expected_audio
        else:
            self._synthesize(sentence, expected_audio)
            wav_path = expected_audio
        duration = wav_duration(wav_path) + self.config.scene_padding

        image = self._select_image(index, sentence, own_images)

        motion_video = self._select_motion_video(
            index=index,
            sentence=sentence,
            image=image,
            duration=duration,
        )
        if motion_video:
            motion_video = self._loopable(motion_video, duration)
            input_args = ["-stream_loop", "-1", "-i", str(motion_video)]
            vf = self._video_filter()
        elif image and self.config.motion:
            input_args = ["-i", str(image)]
            vf = self._motion_filter(index, duration)
        elif image:
            input_args = ["-loop", "1", "-framerate", str(self.config.fps), "-i", str(image)]
            vf = self._still_filter()
        else:
            input_args = [
                "-f",
                "lavfi",
                "-i",
                f"color=c={self.config.background}:s={self.config.width}x{self.config.height}:r={self.config.fps}",
            ]
            vf = self._still_filter()
        run_command(
            [
                self.ffmpeg,
                "-y",
                "-loglevel",
                "error",
                *input_args,
                "-i",
                str(wav_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                vf,
                "-af",
                "apad",
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                self.config.preset,
                "-crf",
                str(self.config.crf),
                "-r",
                str(self.config.fps),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-shortest",
                str(clip_path),
            ]
        )
        return {
            "index": index,
            "sentence": sentence,
            "audio": str(wav_path),
            "image": str(image) if image else None,
            "motion_video": str(motion_video) if motion_video else None,
            "clip": str(clip_path),
            "duration": round(duration, 3),
        }

    def _select_motion_video(
        self,
        *,
        index: int,
        sentence: str,
        image: Path | None,
        duration: float,
    ) -> Path | None:
        if not self.config.motion or self.config.video_provider != "runway" or self.config.dry_run:
            if self.config.video_provider == "runway" and self.config.dry_run:
                LOGGER.info("[%d] dry-run: Runway motion clip planned", index + 1)
            return None

        visual = self._visual_prompts[index] if index < len(self._visual_prompts) else sentence
        director_note = ""
        if index < len(self._director_scenes):
            item = self._director_scenes[index]
            if isinstance(item, dict):
                visual = str(item.get("visual") or visual)
                director_note = f"{item.get('beat', '')}; transition {item.get('transition', 'cut')}; energy {item.get('energy', 'curious')}"
        bible_obj = self._story_context.get("visual_bible", {})
        if not isinstance(bible_obj, dict):
            bible_obj = {}
        shot = plan_shot(index, sentence, self._previous_shot)
        self._previous_shot = shot
        prompt = build_prompt(
            visual=visual,
            sentence=sentence,
            bible=bible_obj,
            plan=shot,
            first=index == 0,
            director_note=director_note,
        )
        prompt_hash = hashlib.sha256(
            f"{self.config.video_model}\0{self.config.video_provider}\0{prompt}".encode()
        ).hexdigest()[:12]
        output = self.config.work_dir / f"motion-{index:03d}-{prompt_hash}.mp4"
        if output.exists():
            try:
                self._validate_motion_clip(output)
                return output
            except RenderError as exc:
                LOGGER.warning("[%d] cached AI clip is unusable (%s); regenerating", index + 1, exc)
                output.unlink(missing_ok=True)
        if image is None:
            LOGGER.info("[%d] no scene image; asking Runway for text-to-video instead", index + 1)

        LOGGER.info("[%d] generating full-motion video clip (%s)", index + 1, shot.shot)
        ratio = "1280:720" if self.config.width >= self.config.height else "720:1280"
        provider = RunwayVideoProvider(model=self.config.video_model, ratio=ratio)
        try:
            result = provider.generate(prompt=prompt, image=image, output=output, duration=duration, retries=self.config.runway_retries)
            self._validate_motion_clip(result)
            return result
        except VideoProviderError as exc:
            if exc.fatal:
                raise RenderError(str(exc)) from exc
            LOGGER.warning("[%d] %s - using the local motion fallback for this scene", index + 1, exc)
        except RenderError as exc:  # clip downloaded but broken: never let it into the edit
            output.unlink(missing_ok=True)
            LOGGER.warning("[%d] %s - using the local motion fallback for this scene", index + 1, exc)
        return None

    def _validate_motion_clip(self, path: Path) -> float:
        """Reject broken provider output before it reaches the edit. Returns the clip length in seconds."""
        if not path.exists() or path.stat().st_size < 20_000:
            raise RenderError(f"AI video output is missing or unexpectedly small: {path.name}")
        length = probe_duration(self.ffmpeg, path)
        if length is None:
            raise RenderError(f"AI video output is not a readable video: {path.name}")
        if length < 1.0:
            raise RenderError(f"AI video output is too short ({length:.2f}s): {path.name}")
        return length

    def _loopable(self, clip: Path, duration: float) -> Path:
        """Return a clip that repeats without a visible jump when the narration outlasts it.

        Playing the clip forward then backward makes the repeat seamless instead of snapping to frame one.
        """
        length = probe_duration(self.ffmpeg, clip)
        if length is None or duration <= length + 0.05:
            return clip
        boomerang = clip.with_name(clip.stem + "-loop.mp4")
        if not boomerang.exists():
            temporary = boomerang.with_name(boomerang.stem + ".tmp.mp4")
            run_command(
                [
                    self.ffmpeg, "-y", "-loglevel", "error", "-i", str(clip),
                    "-filter_complex", "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]",
                    "-map", "[v]", "-an", "-c:v", "libx264", "-preset", self.config.preset,
                    "-crf", str(self.config.crf), "-pix_fmt", "yuv420p", "-f", "mp4", str(temporary),
                ]
            )
            temporary.replace(boomerang)
        return boomerang

    def _still_filter(self) -> str:
        return (
            f"scale={self.config.width}:{self.config.height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={self.config.width}:{self.config.height},setsar=1,format=yuv420p"
        )

    def _video_filter(self) -> str:
        return (
            f"scale={self.config.width}:{self.config.height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={self.config.width}:{self.config.height},setsar=1,format=yuv420p"
        )

    def _motion_filter(self, index: int, duration: float) -> str:
        """Apply a gentle Ken Burns move so still images feel alive."""
        w, h, fps = self.config.width, self.config.height, self.config.fps
        frames = max(2, round(duration * fps))
        strength = self.config.motion_strength
        big_w, big_h = round(w * 1.5), round(h * 1.5)
        variant = index % 4
        if variant == 0:
            z = f"1+{strength}*on/{frames}"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif variant == 1:
            z = f"{1 + strength}-{strength}*on/{frames}"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif variant == 2:
            z = f"{1 + strength}"
            x = f"(iw-iw/zoom)*on/{frames}"
            y = "ih/2-(ih/zoom/2)"
        else:
            z = f"{1 + strength}"
            x = f"(iw-iw/zoom)*(1-on/{frames})"
            y = "ih/2-(ih/zoom/2)"
        return (
            f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
            f"crop={big_w}:{big_h},setsar=1,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
            "format=yuv420p"
        )

    def _load_visual_prompts(self, sentences: list[str], script_hash: str) -> list[str]:
        """Build one cached visual plan. Creator Pro prefers Claude as the story-level director."""
        director_mode = self.config.video_provider == "runway" and self.config.motion
        # Prompts are only used for AI images or Runway clips. Don't upload the script to an AI service otherwise.
        needs_prompts = self.config.use_ai_images or director_mode
        if self.config.dry_run or not self.config.smart_prompts or not needs_prompts:
            self._story_context = {}
            self._director_scenes = []
            return list(sentences)
        cache = self.config.work_dir / "visual_prompts.json"
        provider = self.config.director_provider
        if provider == "auto":
            if os.getenv("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.getenv("POLLINATIONS_API_KEY"):
                provider = "pollinations"
            else:
                provider = "none"
        if provider == "none":
            self._story_context = {}
            self._director_scenes = []
            return list(sentences)
        analysis_hash = hashlib.sha256(
            f"storyboard-v5\0{script_hash}\0{self.config.image_style}\0{provider}\0{self.config.director_model}\0{director_mode}".encode("utf-8")
        ).hexdigest()
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("analysis_hash") == analysis_hash and len(cached.get("prompts", [])) == len(sentences):
                self._story_context = cached.get("storyboard", {})
                self._director_scenes = [x for x in cached.get("director_scenes", []) if isinstance(x, dict)]
                return [str(prompt) for prompt in cached["prompts"]]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        try:
            LOGGER.info("Directing the full story for visual continuity (%s)...", provider)
            if director_mode and provider == "anthropic":
                plan = plan_cinematic_storyboard(
                    sentences,
                    image_style=self.config.image_style,
                    provider="anthropic",
                    model=self.config.director_model,
                    hf_token=self.config.hf_token,
                )
                self._story_context = plan.get("storyboard", {})
                self._director_scenes = [x for x in plan.get("scenes", []) if isinstance(x, dict)]
                prompts = [str(scene.get("visual") or sentences[i]) for i, scene in enumerate(self._director_scenes)]
            else:
                model = "openai"
                if provider == "anthropic":
                    model = self.config.director_model
                elif provider == "huggingface":
                    if self.config.director_model.startswith("claude"):
                        raise RuntimeError("Set --director-model to a Hugging Face model id for the huggingface director.")
                    model = self.config.director_model
                plan = write_storyboard(
                    sentences,
                    image_style=self.config.image_style,
                    provider=provider,
                    model=model,
                    hf_token=self.config.hf_token,
                )
                self._story_context = plan.get("storyboard", {})
                self._director_scenes = []
                prompts = [str(prompt) for prompt in plan.get("prompts", [])]
            if len(prompts) != len(sentences):
                raise RuntimeError("director returned the wrong number of scene prompts")
        except Exception as exc:
            LOGGER.warning("Smart director unavailable (%s); using narration text and deterministic shots.", exc)
            self._story_context = {}
            self._director_scenes = []
            return list(sentences)
        fallbacks = sum(1 for prompt, sentence in zip(prompts, sentences) if prompt == sentence)
        if fallbacks:
            LOGGER.warning(
                "%d of %d scenes used narration text as the prompt; they will be retried on the next run.",
                fallbacks, len(sentences),
            )
            return prompts
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({
                "analysis_hash": analysis_hash,
                "script_hash": script_hash,
                "storyboard": self._story_context,
                "director_scenes": self._director_scenes,
                "prompts": prompts,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(cache)
        return prompts

    def _synthesize(self, text: str, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        mp3 = output.with_suffix(".mp3")
        if self.config.tts_provider == "huggingface":
            try:
                audio_bytes = synthesize_huggingface(
                    text,
                    model=self.config.hf_tts_model,
                    voice=self.config.voice,
                    hf_token=self.config.hf_token,
                )
            except OnlineAIError as exc:
                raise RenderError(str(exc)) from exc
            source = output.with_suffix(".audio")
            source.write_bytes(audio_bytes)
        else:
            source = mp3
            self._run_edge_tts(text, mp3)
        run_command([self.ffmpeg, "-y", "-loglevel", "error", "-i", str(source), str(output)])
        mp3.unlink(missing_ok=True)
        if source != mp3:
            source.unlink(missing_ok=True)

    def _run_edge_tts(self, text: str, mp3: Path) -> None:
        """Call edge-tts with the text in a file, retrying transient failures."""
        text_file = mp3.with_suffix(".txt")
        text_file.write_text(text, encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            self.config.voice,
            f"--rate={self.config.voice_rate}",
            "--file",
            str(text_file),
            "--write-media",
            str(mp3),
        ]
        attempts = 4
        try:
            for attempt in range(1, attempts + 1):
                try:
                    run_command(command)
                    return
                except CommandError:
                    if attempt == attempts:
                        raise
                    LOGGER.warning("Voice request failed (attempt %d/%d); retrying...", attempt, attempts)
                    time.sleep(3 * attempt)
        finally:
            text_file.unlink(missing_ok=True)

    def _select_image(self, index: int, sentence: str, own_images: list[Path]) -> Path | None:
        if self.config.use_ai_images:
            visual = self._visual_prompts[index] if index < len(self._visual_prompts) else sentence
            bible = json.dumps(
                self._story_context.get("visual_bible", {}),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            composition = "landscape 16:9 composition" if self.config.width >= self.config.height else "vertical 9:16 composition"
            prompt = (
                f"Story continuity bible: {bible}. Shot direction: {visual}. "
                f"{self.config.image_style}, {composition}, preserve the same recurring subjects and locations, "
                "photorealistic, physically plausible, no text, no letters, no logos, no watermark"
            )
            prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
            ai_path = self.config.ai_images_dir / f"scene-{index:03d}-{prompt_hash}.jpg"
            if not ai_path.exists() and not self.config.dry_run and not self._images_disabled:
                LOGGER.info("[%d] generating image", index + 1)
                self._generate_image(prompt, ai_path, self.config.seed + index)
                self._track_image_result(ai_path)
            if ai_path.exists():
                return ai_path
        if own_images:
            return own_images[index % len(own_images)]
        LOGGER.warning("[%d] no image available; using background", index + 1)
        return None

    def _track_image_result(self, path: Path) -> None:
        """After 3 scenes in a row with no picture, stop asking: the service is down or needs a key, and every
        further scene would only add minutes of retries before ending up with a plain background anyway."""
        self._image_failures = 0 if path.exists() else self._image_failures + 1
        if self._image_failures >= 3 and not self._images_disabled:
            self._images_disabled = True
            LOGGER.warning(
                "AI images failed for 3 scenes in a row, so the rest use your own images or a plain background. "
                "Get a free key at https://enter.pollinations.ai and put POLLINATIONS_API_KEY=... in the .env file, "
                "or untick 'AI images'."
            )

    def _generate_image(self, prompt: str, output: Path, seed: int) -> None:
        encoded_prompt = urllib.parse.quote(prompt, safe="")
        query = urllib.parse.urlencode(
            {
                "model": self.config.image_model,
                "width": self.config.width,
                "height": self.config.height,
                "nologo": "true",
                "enhance": "true",
                "seed": seed,
            }
        )
        # The current endpoint supports selectable models such as flux. Keep the
        # older public endpoint as a no-key fallback for existing installations.
        urls = [
            f"https://gen.pollinations.ai/image/{encoded_prompt}?{query}",
            (
                "https://image.pollinations.ai/prompt/"
                + encoded_prompt
                + "?"
                + urllib.parse.urlencode(
                    {
                        "width": self.config.width,
                        "height": self.config.height,
                        "nologo": "true",
                        "seed": seed,
                    }
                )
            ),
        ]
        headers = {"User-Agent": "faceless-video-generator/1.5"}
        api_key = os.getenv("POLLINATIONS_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        last_error: Exception | None = None
        for url in urls:
            for attempt in range(self.config.image_retries):
                try:
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=120) as response:
                        content_type = response.headers.get("Content-Type", "")
                        data = response.read()
                    if not content_type.startswith("image/") or len(data) < 5_000:
                        raise ValueError(f"unexpected response ({content_type}, {len(data)} bytes)")
                    temp_path = output.with_suffix(".tmp")
                    temp_path.write_bytes(data)
                    temp_path.replace(output)
                    if attempt:
                        LOGGER.info("Image generated after %d retries", attempt)
                    return
                except urllib.error.HTTPError as exc:
                    last_error = exc
                    # Authentication failures will not improve by retrying.
                    if exc.code in {401, 403}:
                        LOGGER.warning("Image model endpoint requires POLLINATIONS_API_KEY.")
                        break
                    if attempt + 1 < self.config.image_retries:
                        LOGGER.warning(
                            "Image attempt %d/%d failed: %s",
                            attempt + 1,
                            self.config.image_retries,
                            exc,
                        )
                        time.sleep(self.config.image_delay)
                except Exception as exc:
                    last_error = exc
                    if attempt + 1 < self.config.image_retries:
                        LOGGER.warning(
                            "Image attempt %d/%d failed: %s",
                            attempt + 1,
                            self.config.image_retries,
                            exc,
                        )
                        time.sleep(self.config.image_delay)
            LOGGER.warning("Image endpoint failed; trying the compatibility fallback.")
        LOGGER.warning("AI image generation skipped: %s", last_error)

    def _concat_clips(self, concat_path: Path, output: Path) -> None:
        run_command(
            [
                self.ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                str(output),
            ],
            cwd=self.config.work_dir,
        )

    def _prepare_music(self, duration: float) -> Path | None:
        if self.config.dry_run:
            return None
        if self.config.music:
            if not self.config.music.is_file():
                raise RenderError(f"Music file not found: {self.config.music}")
            return self.config.music
        if self.config.music_url:
            destination = self.config.work_dir / "downloaded-music"
            try:
                return download_music(self.config.music_url, destination)
            except OSError as exc:
                raise RenderError(f"Could not download music: {exc}") from exc
        if self.config.auto_music:
            return create_ambient_bed(self.ffmpeg, self.config.work_dir / "ambient-bed.wav", duration)
        return None

    def _finalize_video(
        self,
        joined: Path,
        subtitles: Path,
        output: Path,
        music: Path | None,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.mp4")
        command = [
            self.ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(joined),
        ]
        if music:
            command += ["-stream_loop", "-1", "-i", str(music)]
            audio_filter = (
                f"[1:a]volume={self.config.music_volume:.3f}[music];"
                "[music][0:a]sidechaincompress=threshold=0.02:ratio=8:"
                "attack=20:release=250[ducked];"
                "[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:"
                "normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
            )
        else:
            audio_filter = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        command += [
            "-filter_complex",
            audio_filter,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-vf",
            f"ass={subtitles.name}",
            "-c:v",
            "libx264",
            "-preset",
            self.config.preset,
            "-crf",
            str(self.config.crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(temporary),
        ]
        run_command(command, cwd=self.config.work_dir)
        temporary.replace(output)

    def _validate_final_video(self, path: Path, *, expected_duration: float) -> None:
        """Perform a cheap final QA pass so a successful FFmpeg exit cannot hide a broken deliverable."""
        if not path.exists() or path.stat().st_size < 1_000:
            raise RenderError("Final video is missing or empty.")
        actual = probe_duration(self.ffmpeg, path)
        if actual is None or actual < 1.0:
            raise RenderError("Final video cannot be read as a video file.")
        if actual + 0.75 < expected_duration:
            raise RenderError(f"Final video is too short ({actual:.2f}s; expected about {expected_duration:.2f}s).")
        try:
            run_command([self.ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
        except CommandError as exc:
            raise RenderError(f"Final video failed FFmpeg decode validation: {exc}") from exc

    def _write_subtitles(self, scenes: Iterable[dict[str, object]], output: Path) -> None:
        current = 0.0
        blocks = []
        for number, scene in enumerate(scenes, 1):
            duration = float(scene["duration"])
            blocks.append(
                f"{number}\n{srt_time(current)} --> {srt_time(current + duration)}\n"
                f"{scene['sentence']}\n"
            )
            current += duration
        output.write_text("\n".join(blocks), encoding="utf-8")

    def _read_script(self) -> str:
        try:
            return clean_narration(self.config.script.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RenderError(f"Script not found: {self.config.script}") from exc

    def _find_images(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in DEFAULT_IMAGE_EXTENSIONS
        )

    def _load_manifest(self) -> dict[str, object]:
        path = self.config.work_dir / "manifest.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_manifest(
        self,
        script_hash: str,
        config: dict[str, object],
        scenes: list[dict[str, object]],
        *,
        completed: bool = False,
    ) -> None:
        payload = {
            "version": 1,
            "script_hash": script_hash,
            "config": config,
            "scenes": scenes,
            "completed": completed,
        }
        path = self.config.work_dir / "manifest.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)


def split_sentences(text: str) -> list[str]:
    """Split narration while preserving punctuation and handling line breaks."""
    normalized = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]


def group_sentences(sentences: list[str], min_words: int) -> list[str]:
    """Merge short neighbouring sentences so each image stays on screen long enough.

    A scene closes once it has at least ``min_words`` words. A short leftover at
    the end is attached to the previous scene instead of becoming a flash cut.
    """
    if min_words <= 0:
        return list(sentences)
    scenes: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        current.append(sentence)
        if sum(len(part.split()) for part in current) >= min_words:
            scenes.append(" ".join(current))
            current = []
    if current:
        tail = " ".join(current)
        if scenes and len(tail.split()) < min_words // 2:
            scenes[-1] = f"{scenes[-1]} {tail}"
        else:
            scenes.append(tail)
    return scenes


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except (wave.Error, OSError) as exc:
        raise RenderError(f"Could not read generated audio {path}: {exc}") from exc


def srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"