"""Flask routes and helpers for DrinkingFountain web UI."""

from __future__ import annotations

import logging
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from drinkingfountain.config import Config
from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import Dialogue, Scene
from drinkingfountain.services import (
    RenderCancelled,
    RenderService,
    TimingBlock,
    VoiceService,
)
from drinkingfountain.tts import CachedTTSBackend, PiperTTSBackend
from drinkingfountain.voices import VoiceManager

logger = logging.getLogger(__name__)

RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=2)
LIVE_EXECUTOR = ThreadPoolExecutor(max_workers=2)


@dataclass
class RenderControl:
    """Cooperative controls for a background render job."""

    pause_event: threading.Event
    cancel_event: threading.Event


class RenderStore:
    """TTL-based store for render results with automatic eviction."""

    MAX_ENTRIES = 50
    TTL_SECONDS = 1800  # 30 minutes
    TERMINAL_STATUSES = {"complete", "failed", "cancelled"}

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}
        self._controls: dict[str, RenderControl] = {}
        self._lock = threading.Lock()

    def put(
        self,
        render_id: str,
        audio_path: Path,
        timing_blocks: list[TimingBlock] | None,
        audio_format: str,
        title: str,
        duration: float,
        download_name: str | None = None,
    ) -> None:
        timing_json = None
        if timing_blocks is not None:
            timing_json = {
                "title": title,
                "duration": duration,
                "blocks": [asdict(b) for b in timing_blocks],
            }

        with self._lock:
            self._store[render_id] = {
                "audio_path": audio_path,
                "timing_json": timing_json,
                "format": audio_format,
                "created_at": time.time(),
                "updated_at": time.time(),
                "status": "complete",
                "progress": {
                    "stage": "complete",
                    "message": "Render complete",
                    "percent": 100,
                },
                "error": None,
                "title": title,
                "duration": duration,
                "download_name": download_name
                or build_download_name(title, audio_format),
            }
            self._evict()

    def put_pending(
        self,
        render_id: str,
        audio_path: Path,
        audio_format: str,
        download_name: str,
    ) -> None:
        with self._lock:
            now = time.time()
            self._controls[render_id] = RenderControl(
                pause_event=threading.Event(),
                cancel_event=threading.Event(),
            )
            self._store[render_id] = {
                "audio_path": audio_path,
                "timing_json": None,
                "format": audio_format,
                "created_at": now,
                "updated_at": now,
                "status": "queued",
                "progress": {
                    "stage": "queued",
                    "message": "Queued",
                    "percent": 0,
                },
                "error": None,
                "title": "Untitled",
                "duration": 0.0,
                "download_name": download_name,
            }
            self._evict()

    def update_progress(self, render_id: str, progress: dict[str, object]) -> None:
        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return
            if entry["status"] in {"complete", "failed", "cancelled"}:
                return
            if entry["status"] != "paused":
                entry["status"] = "running"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                **progress,
            }

    def complete(
        self,
        render_id: str,
        timing_blocks: list[TimingBlock] | None,
        title: str,
        duration: float,
    ) -> None:
        timing_json = None
        if timing_blocks is not None:
            timing_json = {
                "title": title,
                "duration": duration,
                "blocks": [asdict(b) for b in timing_blocks],
            }

        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return
            entry["timing_json"] = timing_json
            entry["status"] = "complete"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                "stage": "complete",
                "message": "Render complete",
                "percent": 100,
            }
            entry["error"] = None
            entry["title"] = title
            entry["duration"] = duration
            self._controls.pop(render_id, None)

    def fail(self, render_id: str, error: str) -> None:
        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return
            entry["status"] = "failed"
            entry["updated_at"] = time.time()
            entry["error"] = error
            entry["progress"] = {
                "stage": "failed",
                "message": error,
                "percent": entry.get("progress", {}).get("percent", 0),
            }
            audio_path = entry.get("audio_path")
            if isinstance(audio_path, Path) and audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            self._remove_temp_wav(audio_path)
            self._controls.pop(render_id, None)

    def pause(self, render_id: str) -> bool:
        with self._lock:
            entry = self._store.get(render_id)
            control = self._controls.get(render_id)
            if entry is None or control is None:
                return False
            if entry["status"] not in {"queued", "running", "paused"}:
                return False
            control.pause_event.set()
            entry["status"] = "paused"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "paused",
                "message": "Render paused",
            }
            return True

    def resume(self, render_id: str) -> bool:
        with self._lock:
            entry = self._store.get(render_id)
            control = self._controls.get(render_id)
            if entry is None or control is None:
                return False
            if entry["status"] != "paused":
                return False
            control.pause_event.clear()
            entry["status"] = "running"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "rendering",
                "message": "Render resumed",
            }
            return True

    def request_cancel(self, render_id: str) -> bool:
        with self._lock:
            entry = self._store.get(render_id)
            control = self._controls.get(render_id)
            if entry is None or control is None:
                return False
            if entry["status"] in {"complete", "failed", "cancelled"}:
                return False
            control.cancel_event.set()
            control.pause_event.clear()
            entry["status"] = "cancelling"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "cancelling",
                "message": "Cancelling render",
            }
            return True

    def cancelled(self, render_id: str) -> None:
        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return
            entry["status"] = "cancelled"
            entry["updated_at"] = time.time()
            entry["error"] = None
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "cancelled",
                "message": "Render cancelled",
            }
            audio_path = entry.get("audio_path")
            if isinstance(audio_path, Path) and audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            self._remove_temp_wav(audio_path)
            self._controls.pop(render_id, None)

    def get_control(self, render_id: str) -> RenderControl | None:
        with self._lock:
            return self._controls.get(render_id)

    def get(self, render_id: str) -> dict | None:
        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return None
            if entry["status"] in self.TERMINAL_STATUSES and (
                time.time() - entry.get("updated_at", entry["created_at"])
                > self.TTL_SECONDS
            ):
                self._remove(render_id)
                return None
            return entry

    def _evict(self) -> None:
        now = time.time()
        expired = [
            rid
            for rid, e in self._store.items()
            if e["status"] in self.TERMINAL_STATUSES
            and now - e.get("updated_at", e["created_at"]) > self.TTL_SECONDS
        ]
        for rid in expired:
            self._remove(rid)

        if len(self._store) > self.MAX_ENTRIES:
            by_age = sorted(
                self._store.items(),
                key=lambda x: x[1].get("updated_at", x[1]["created_at"]),
            )
            excess = len(self._store) - self.MAX_ENTRIES
            for rid, _ in by_age[:excess]:
                self._remove(rid)

    def _remove(self, render_id: str) -> None:
        entry = self._store.pop(render_id, None)
        self._controls.pop(render_id, None)
        if entry is None:
            return
        audio_path = entry.get("audio_path")
        if audio_path and isinstance(audio_path, Path) and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass
        self._remove_temp_wav(audio_path)

    def _remove_temp_wav(self, audio_path: object) -> None:
        if audio_path and isinstance(audio_path, Path):
            temp_wav_path = audio_path.with_suffix(".tmp.wav")
            if temp_wav_path.exists():
                try:
                    temp_wav_path.unlink()
                except OSError:
                    pass


render_store = RenderStore()


class LiveRenderStore:
    """In-memory store for one-scene-lookahead live preview sessions."""

    MAX_ENTRIES = 20
    TTL_SECONDS = 1800
    TERMINAL_STATUSES = {"complete", "failed", "cancelled"}

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}
        self._controls: dict[str, RenderControl] = {}
        self._lock = threading.Lock()

    def create(
        self,
        live_id: str,
        scenes: list[dict[str, object]],
        script_title: str,
        script_text: str,
        config_obj: Config,
        output_format: str,
        download_requested: bool,
    ) -> None:
        with self._lock:
            now = time.time()
            self._controls[live_id] = RenderControl(
                pause_event=threading.Event(),
                cancel_event=threading.Event(),
            )
            self._store[live_id] = {
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "error": None,
                "progress": {
                    "stage": "queued",
                    "message": "Preparing live preview",
                    "percent": 0,
                },
                "scenes": scenes,
                "script_title": script_title,
                "script_text": script_text,
                "config": config_obj,
                "format": output_format,
                "download_requested": download_requested,
                "generation": 0,
                "requested_scene": 0,
                "rendering_scene": None,
                "ready_scenes": {},
            }
            self._evict()

    def get(self, live_id: str) -> dict | None:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None:
                return None
            if entry["status"] in self.TERMINAL_STATUSES and (
                time.time() - entry.get("updated_at", entry["created_at"])
                > self.TTL_SECONDS
            ):
                self._remove(live_id)
                return None
            return entry

    def snapshot(self, live_id: str) -> dict | None:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None:
                return None
            return {
                "status": entry["status"],
                "live_id": live_id,
                "error": entry["error"],
                "progress": entry["progress"],
                "scenes": entry["scenes"],
                "script_title": entry["script_title"],
                "download_requested": entry["download_requested"],
                "requested_scene": entry["requested_scene"],
                "rendering_scene": entry["rendering_scene"],
                "ready_scenes": {
                    str(idx): {
                        "scene_index": idx,
                        "audio_url": f"/live/{live_id}/scene/{idx}/audio",
                        "timing": result["timing"],
                        "duration": result["duration"],
                    }
                    for idx, result in entry["ready_scenes"].items()
                },
            }

    def get_control(self, live_id: str) -> RenderControl | None:
        with self._lock:
            return self._controls.get(live_id)

    def request_scene(self, live_id: str, scene_index: int) -> int | None:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None:
                return None
            if scene_index < 0 or scene_index >= len(entry["scenes"]):
                return None
            if entry["status"] in self.TERMINAL_STATUSES:
                return None
            entry["generation"] += 1
            entry["requested_scene"] = scene_index
            entry["rendering_scene"] = None
            entry["status"] = "queued"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                "stage": "queued",
                "message": f"Queued scene {scene_index + 1}/{len(entry['scenes'])}",
                "current_scene": scene_index + 1,
                "total_scenes": len(entry["scenes"]),
                "percent": 0,
            }
            return entry["generation"]

    def mark_rendering(
        self, live_id: str, scene_index: int, generation: int, message: str
    ) -> bool:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None or entry["generation"] != generation:
                return False
            if entry["status"] in self.TERMINAL_STATUSES:
                return False
            entry["status"] = "running"
            entry["rendering_scene"] = scene_index
            entry["updated_at"] = time.time()
            entry["progress"] = {
                "stage": "rendering",
                "message": message,
                "current_scene": scene_index + 1,
                "total_scenes": len(entry["scenes"]),
                "scene_heading": entry["scenes"][scene_index]["heading"],
                "percent": int((scene_index / max(len(entry["scenes"]), 1)) * 100),
            }
            return True

    def store_scene(
        self,
        live_id: str,
        scene_index: int,
        generation: int,
        audio_path: Path,
        timing_blocks: list[TimingBlock],
        duration: float,
    ) -> bool:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None or entry["generation"] != generation:
                self._unlink(audio_path)
                return False
            if entry["status"] in self.TERMINAL_STATUSES:
                self._unlink(audio_path)
                return False
            entry["ready_scenes"][scene_index] = {
                "audio_path": audio_path,
                "timing": [asdict(block) for block in timing_blocks],
                "duration": duration,
            }
            entry["rendering_scene"] = None
            entry["updated_at"] = time.time()
            if scene_index >= len(entry["scenes"]) - 1:
                entry["status"] = "complete"
                entry["progress"] = {
                    "stage": "complete",
                    "message": "Live preview ready",
                    "percent": 100,
                }
                self._controls.pop(live_id, None)
            else:
                entry["status"] = "running"
                entry["progress"] = {
                    "stage": "ready",
                    "message": f"Scene {scene_index + 1} ready",
                    "current_scene": scene_index + 1,
                    "total_scenes": len(entry["scenes"]),
                    "scene_heading": entry["scenes"][scene_index]["heading"],
                    "percent": int(
                        ((scene_index + 1) / max(len(entry["scenes"]), 1)) * 100
                    ),
                }
            return True

    def fail(self, live_id: str, error: str) -> None:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None:
                return
            entry["status"] = "failed"
            entry["updated_at"] = time.time()
            entry["error"] = error
            entry["progress"] = {
                "stage": "failed",
                "message": error,
                "percent": entry.get("progress", {}).get("percent", 0),
            }
            self._controls.pop(live_id, None)

    def request_cancel(self, live_id: str) -> bool:
        with self._lock:
            entry = self._store.get(live_id)
            control = self._controls.get(live_id)
            if entry is None or control is None:
                return False
            if entry["status"] in self.TERMINAL_STATUSES:
                return False
            control.cancel_event.set()
            control.pause_event.clear()
            entry["status"] = "cancelling"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "cancelling",
                "message": "Cancelling live preview",
            }
            return True

    def cancelled(self, live_id: str) -> None:
        with self._lock:
            entry = self._store.get(live_id)
            if entry is None:
                return
            entry["status"] = "cancelled"
            entry["updated_at"] = time.time()
            entry["progress"] = {
                **entry.get("progress", {}),
                "stage": "cancelled",
                "message": "Live preview cancelled",
            }
            self._controls.pop(live_id, None)

    def _evict(self) -> None:
        now = time.time()
        expired = [
            live_id
            for live_id, entry in self._store.items()
            if entry["status"] in self.TERMINAL_STATUSES
            and now - entry.get("updated_at", entry["created_at"]) > self.TTL_SECONDS
        ]
        for live_id in expired:
            self._remove(live_id)

        if len(self._store) > self.MAX_ENTRIES:
            by_age = sorted(
                self._store.items(),
                key=lambda x: x[1].get("updated_at", x[1]["created_at"]),
            )
            for live_id, _ in by_age[: len(self._store) - self.MAX_ENTRIES]:
                self._remove(live_id)

    def _remove(self, live_id: str) -> None:
        entry = self._store.pop(live_id, None)
        self._controls.pop(live_id, None)
        if entry is None:
            return
        for result in entry["ready_scenes"].values():
            self._unlink(result.get("audio_path"))

    def _unlink(self, audio_path: object) -> None:
        if isinstance(audio_path, Path) and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass


live_render_store = LiveRenderStore()


def get_script_text_from_request() -> str:
    """Get script text from textarea data or an uploaded file."""
    script_text = request.form.get("script", "").strip()
    if script_text:
        return script_text

    uploaded = request.files.get("script_file")
    if uploaded and uploaded.filename:
        script_text = uploaded.read().decode("utf-8", errors="replace").strip()
    return script_text


def build_download_name(name: str | None, audio_format: str) -> str:
    """Build a safe browser download filename."""
    stem = (name or "drinkingfountain-render").strip()
    stem = Path(stem).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    if not stem:
        stem = "drinkingfountain-render"
    return f"{stem}.{audio_format}"


def scene_has_dialogue(scene: Scene) -> bool:
    """Return True when a scene has dialogue that can be rendered live."""
    return any(isinstance(block, Dialogue) for block in scene.blocks)


def make_renderer(config_obj: Config) -> RenderService:
    """Build a render service with configured voices for web jobs."""
    piper = PiperTTSBackend(max_text_length=500)
    tts = CachedTTSBackend(piper)
    if not tts.list_voices():
        raise RuntimeError(
            "No voice models installed. Use 'drinkingfountain voices download <voice_id>' to install one."
        )

    voice_mgr = VoiceManager(tts)
    if config_obj.voices:
        for character, voice in config_obj.voices.items():
            voice_mgr.set_character_voice(character, voice)

    return RenderService(
        config=config_obj,
        tts=tts,
        voice_mgr=voice_mgr,
        narrator_cfg=config_obj.narrator,
    )


def render_job(
    render_id: str,
    script_text: str,
    output_path: Path,
    config_obj: Config,
) -> None:
    """Run a render in the background and update the render store."""

    def check_control() -> None:
        control = render_store.get_control(render_id)
        if control is None:
            return
        if control.cancel_event.is_set():
            raise RenderCancelled("Render cancelled")
        while control.pause_event.is_set():
            if control.cancel_event.is_set():
                raise RenderCancelled("Render cancelled")
            time.sleep(0.25)
        if control.cancel_event.is_set():
            raise RenderCancelled("Render cancelled")

    try:
        render_store.update_progress(
            render_id,
            {
                "stage": "initializing",
                "message": "Initializing voices",
                "percent": 0,
            },
        )
        service = make_renderer(config_obj)

        result = service.render_from_string(
            script_text,
            output=str(output_path),
            collect_timing=True,
            progress_callback=lambda progress: render_store.update_progress(
                render_id, progress
            ),
            control_callback=check_control,
        )
        render_store.complete(
            render_id=render_id,
            timing_blocks=result.timing_blocks,
            title=result.script_title,
            duration=result.duration,
        )
    except RenderCancelled:
        logger.info("Render job cancelled: %s", render_id)
        render_store.cancelled(render_id)
    except Exception as e:
        logger.exception("Render job failed")
        render_store.fail(render_id, str(e))


def live_scene_job(
    live_id: str,
    scene_index: int,
    generation: int,
) -> None:
    """Render one live preview scene and then queue one lookahead scene."""

    def check_control() -> None:
        control = live_render_store.get_control(live_id)
        if control is None:
            return
        if control.cancel_event.is_set():
            raise RenderCancelled("Live preview cancelled")

    entry = live_render_store.get(live_id)
    if entry is None:
        return
    if generation != entry["generation"]:
        return

    try:
        scenes: list[dict[str, object]] = entry["scenes"]
        message = f"Rendering scene {scene_index + 1}/{len(scenes)}"
        if not live_render_store.mark_rendering(
            live_id, scene_index, generation, message
        ):
            return

        parser = FountainParser()
        script_obj = parser.parse_string(entry["script_text"])
        source_scene_index = int(
            scenes[scene_index].get("source_scene_index", scene_index)
        )
        scene = script_obj.scenes[source_scene_index]
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav", prefix=f"df_live_{live_id}_{scene_index}_"
        )
        tmp.close()
        output_path = Path(tmp.name)
        service = make_renderer(entry["config"])
        result = service.render_scene(
            scene,
            output=str(output_path),
            collect_timing=True,
            title=entry["script_title"],
            progress_callback=lambda progress: live_render_store.mark_rendering(
                live_id,
                scene_index,
                generation,
                str(progress.get("message") or message),
            ),
            control_callback=check_control,
        )
        stored = live_render_store.store_scene(
            live_id=live_id,
            scene_index=scene_index,
            generation=generation,
            audio_path=output_path,
            timing_blocks=result.timing_blocks or [],
            duration=result.duration,
        )
        if stored and scene_index + 1 < len(scenes):
            next_entry = live_render_store.get(live_id)
            if next_entry is not None and next_entry["generation"] == generation:
                LIVE_EXECUTOR.submit(
                    live_scene_job, live_id, scene_index + 1, generation
                )
    except RenderCancelled:
        logger.info("Live preview cancelled: %s", live_id)
        live_render_store.cancelled(live_id)
    except Exception as e:
        logger.exception("Live scene render failed")
        live_render_store.fail(live_id, str(e))


def build_config_from_form(form: dict) -> Config:
    """Build a Config object from form data, using defaults for missing fields."""
    data: dict = {}

    audio: dict = {}
    if form.get("sample_rate"):
        audio["sample_rate"] = int(form["sample_rate"])
    if form.get("channels"):
        audio["channels"] = form["channels"]
    if "normalize" in form:
        audio["normalize"] = form["normalize"] == "on"
    if form.get("target_level"):
        audio["target_level"] = float(form["target_level"])
    if audio:
        data["audio"] = audio

    timing: dict = {}
    if form.get("pause_between_lines"):
        timing["pause_between_lines"] = float(form["pause_between_lines"])
    if form.get("pause_after_scene_heading"):
        timing["pause_after_scene_heading"] = float(form["pause_after_scene_heading"])
    if form.get("pause_between_scenes"):
        timing["pause_between_scenes"] = float(form["pause_between_scenes"])
    if timing:
        data["timing"] = timing

    narrator: dict = {}
    narrator["enabled"] = form.get("narrator_enabled") == "on"
    if form.get("narrator_voice"):
        narrator["voice"] = form["narrator_voice"]
    if "expand_int_ext" in form:
        narrator["expand_int_ext"] = form["expand_int_ext"] == "on"
    if form.get("pause_before_narrative"):
        narrator["pause_before_narrative"] = float(form["pause_before_narrative"])
    if form.get("pause_after_narrative"):
        narrator["pause_after_narrative"] = float(form["pause_after_narrative"])
    data["narrator"] = narrator

    # Voice overrides: expect voice_char_N and voice_id_N pairs
    voices: dict[str, str] = {}
    for key in form:
        if key.startswith("voice_char_"):
            idx = key[len("voice_char_") :]
            char_name = form[key].strip()
            voice_id = form.get(f"voice_id_{idx}", "").strip()
            if char_name and voice_id:
                voices[char_name] = voice_id
    if voices:
        data["voices"] = voices

    return Config.from_dict(data) if data else Config()


def register_routes(app: Flask) -> None:
    """Register all routes on the Flask app."""

    @app.route("/")
    def index():  # type: ignore[no-untyped-def]
        return render_template("index.html")

    @app.route("/api/health")
    def health():  # type: ignore[no-untyped-def]
        try:
            piper = PiperTTSBackend(max_text_length=500)
            available = len(piper.list_voices()) > 0
        except Exception:
            available = False
        return jsonify({"status": "healthy", "piper_available": available})

    @app.route("/api/voices")
    def voices():  # type: ignore[no-untyped-def]
        try:
            service = VoiceService()
            voice_list = service.list_voices()
            return jsonify({"voices": sorted(voice_list)})
        except Exception as e:
            return jsonify({"voices": [], "error": str(e)})

    @app.route("/api/script-info", methods=["POST"])
    def script_info():  # type: ignore[no-untyped-def]
        script_text = get_script_text_from_request()
        if not script_text:
            return jsonify({"error": "No script provided."}), 400

        try:
            parser = FountainParser()
            script_obj = parser.parse_string(script_text)
            characters = sorted(script_obj.characters)

            piper = PiperTTSBackend(max_text_length=500)
            voice_mgr = VoiceManager(piper)
            narrator_voice = request.form.get("narrator_voice", "").strip()
            if narrator_voice:
                voice_mgr.set_narrator_voice(narrator_voice)

            voices = sorted(piper.list_voices())
            assignments: dict[str, str] = {}
            for character in characters:
                try:
                    assignments[character] = voice_mgr.get_voice_for_character(
                        character
                    )
                except (RuntimeError, ValueError):
                    assignments[character] = ""

            return jsonify(
                {
                    "characters": characters,
                    "voices": voices,
                    "assignments": assignments,
                    "scene_count": len(script_obj.scenes),
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/render", methods=["POST"])
    def render():  # type: ignore[no-untyped-def]
        script_text = get_script_text_from_request()
        if not script_text:
            return jsonify({"error": "No script provided."}), 400

        output_format = request.form.get("output_format", "wav")
        if output_format not in ("wav", "mp3"):
            output_format = "wav"
        live_preview = request.form.get("live_preview") == "on"
        create_download = request.form.get("create_download") == "on"

        try:
            config_obj = build_config_from_form(request.form)
            errors = config_obj.validate()
            if errors:
                return jsonify({"error": "; ".join(errors)}), 400
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid configuration: {e}"}), 400

        if live_preview:
            try:
                parser = FountainParser()
                script_obj = parser.parse_string(script_text)
                if not script_obj.scenes:
                    return jsonify({"error": "No scenes found in script."}), 400
                renderable_scenes = [
                    (source_idx, scene)
                    for source_idx, scene in enumerate(script_obj.scenes)
                    if scene_has_dialogue(scene)
                ]
                if not renderable_scenes:
                    return jsonify({"error": "No dialogue found in script."}), 400
                scenes: list[dict[str, object]] = [
                    {
                        "index": live_idx,
                        "source_scene_index": source_idx,
                        "heading": scene.heading.content,
                        "line_number": scene.heading.line_number,
                    }
                    for live_idx, (source_idx, scene) in enumerate(renderable_scenes)
                ]
            except Exception as e:
                return jsonify({"error": str(e)}), 400

            live_id = uuid.uuid4().hex[:12]
            live_render_store.create(
                live_id=live_id,
                scenes=scenes,
                script_title=script_obj.title or "Untitled",
                script_text=script_text,
                config_obj=config_obj,
                output_format=output_format,
                download_requested=create_download,
            )
            generation = live_render_store.request_scene(live_id, 0)
            if generation is not None:
                LIVE_EXECUTOR.submit(live_scene_job, live_id, 0, generation)
            return jsonify(
                {
                    "status": "queued",
                    "mode": "live",
                    "live_id": live_id,
                    "render_id": live_id,
                    "progress_url": f"/live/{live_id}/state",
                    "scenes": scenes,
                    "script_title": script_obj.title or "Untitled",
                    "download_requested": create_download,
                }
            ), 202

        if not create_download:
            return jsonify({"error": "Select live preview or create download."}), 400

        suffix = f".{output_format}"
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="df_render_"
        )
        tmp.close()
        output_path = Path(tmp.name)
        render_id = uuid.uuid4().hex[:12]
        download_name = build_download_name(
            request.form.get("output_name") or "drinkingfountain-render",
            output_format,
        )

        render_store.put_pending(
            render_id=render_id,
            audio_path=output_path,
            audio_format=output_format,
            download_name=download_name,
        )
        RENDER_EXECUTOR.submit(
            render_job, render_id, script_text, output_path, config_obj
        )

        return jsonify(
            {
                "status": "queued",
                "render_id": render_id,
                "progress_url": f"/progress/{render_id}",
            }
        ), 202

    @app.route("/progress/<render_id>")
    def progress(render_id: str):  # type: ignore[no-untyped-def]
        entry = render_store.get(render_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404

        payload = {
            "status": entry["status"],
            "render_id": render_id,
            "progress": entry["progress"],
            "error": entry["error"],
        }
        if entry["status"] == "complete":
            payload.update(
                {
                    "audio_url": f"/audio/{render_id}",
                    "download_url": f"/download/{render_id}",
                    "timing_url": f"/timing/{render_id}",
                    "duration": entry["duration"],
                    "script_title": entry["title"],
                    "download_name": entry["download_name"],
                }
            )
        return jsonify(payload)

    @app.route("/pause/<render_id>", methods=["POST"])
    def pause(render_id: str):  # type: ignore[no-untyped-def]
        if not render_store.pause(render_id):
            return jsonify({"error": "Render cannot be paused"}), 404
        return jsonify({"status": "paused", "render_id": render_id})

    @app.route("/resume/<render_id>", methods=["POST"])
    def resume(render_id: str):  # type: ignore[no-untyped-def]
        if not render_store.resume(render_id):
            return jsonify({"error": "Render cannot be resumed"}), 404
        return jsonify({"status": "running", "render_id": render_id})

    @app.route("/cancel/<render_id>", methods=["POST"])
    def cancel(render_id: str):  # type: ignore[no-untyped-def]
        if not render_store.request_cancel(render_id) and not (
            live_render_store.request_cancel(render_id)
        ):
            return jsonify({"error": "Render cannot be cancelled"}), 404
        return jsonify({"status": "cancelling", "render_id": render_id})

    @app.route("/live/<live_id>/state")
    def live_state(live_id: str):  # type: ignore[no-untyped-def]
        snapshot = live_render_store.snapshot(live_id)
        if snapshot is None:
            return jsonify({"error": "Not found or expired"}), 404
        return jsonify(snapshot)

    @app.route("/live/<live_id>/play/<int:scene_index>", methods=["POST"])
    def live_play(live_id: str, scene_index: int):  # type: ignore[no-untyped-def]
        generation = live_render_store.request_scene(live_id, scene_index)
        if generation is None:
            return jsonify({"error": "Scene cannot be queued"}), 404
        LIVE_EXECUTOR.submit(live_scene_job, live_id, scene_index, generation)
        return jsonify(
            {
                "status": "queued",
                "live_id": live_id,
                "scene_index": scene_index,
            }
        )

    @app.route("/live/<live_id>/scene/<int:scene_index>/audio")
    def live_scene_audio(live_id: str, scene_index: int):  # type: ignore[no-untyped-def]
        entry = live_render_store.get(live_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404
        result = entry["ready_scenes"].get(scene_index)
        if result is None:
            return jsonify({"error": "Scene audio not ready"}), 404
        audio_path = result["audio_path"]
        if not audio_path.exists():
            return jsonify({"error": "Scene audio file not found"}), 404
        return send_file(audio_path, mimetype="audio/wav")

    @app.route("/audio/<render_id>")
    def audio(render_id: str):  # type: ignore[no-untyped-def]
        entry = render_store.get(render_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404
        audio_path = entry["audio_path"]
        if not audio_path.exists():
            return jsonify({"error": "Audio file not found"}), 404
        mime = "audio/wav" if entry["format"] == "wav" else "audio/mpeg"
        return send_file(audio_path, mimetype=mime)

    @app.route("/download/<render_id>")
    def download(render_id: str):  # type: ignore[no-untyped-def]
        entry = render_store.get(render_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404
        audio_path = entry["audio_path"]
        if entry["status"] != "complete" or not audio_path.exists():
            return jsonify({"error": "Audio file not ready"}), 404
        mime = "audio/wav" if entry["format"] == "wav" else "audio/mpeg"
        return send_file(
            audio_path,
            mimetype=mime,
            as_attachment=True,
            download_name=entry["download_name"],
        )

    @app.route("/timing/<render_id>")
    def timing(render_id: str):  # type: ignore[no-untyped-def]
        entry = render_store.get(render_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404
        if entry["timing_json"] is None:
            return jsonify({"error": "No timing data available"}), 404
        return jsonify(entry["timing_json"])
