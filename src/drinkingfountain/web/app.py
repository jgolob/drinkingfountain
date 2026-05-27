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


def get_script_text_from_request() -> str:
    """Get script text from textarea data or an uploaded file."""
    script_text = request.form.get("script", "").strip()
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

        service = RenderService(
            config=config_obj,
            tts=tts,
            voice_mgr=voice_mgr,
            narrator_cfg=config_obj.narrator,
        )

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

        try:
            config_obj = build_config_from_form(request.form)
            errors = config_obj.validate()
            if errors:
                return jsonify({"error": "; ".join(errors)}), 400
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid configuration: {e}"}), 400

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
        if not render_store.request_cancel(render_id):
            return jsonify({"error": "Render cannot be cancelled"}), 404
        return jsonify({"status": "cancelling", "render_id": render_id})

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
