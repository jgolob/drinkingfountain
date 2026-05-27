"""Flask routes and helpers for DrinkingFountain web UI."""

from __future__ import annotations

import logging
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from drinkingfountain.config import Config
from drinkingfountain.services import RenderService, TimingBlock, VoiceService
from drinkingfountain.tts import CachedTTSBackend, PiperTTSBackend
from drinkingfountain.voices import VoiceManager

logger = logging.getLogger(__name__)

RENDER_TIMEOUT_SECONDS = 300  # 5 minutes


class RenderStore:
    """TTL-based store for render results with automatic eviction."""

    MAX_ENTRIES = 50
    TTL_SECONDS = 1800  # 30 minutes

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()

    def put(
        self,
        render_id: str,
        audio_path: Path,
        timing_blocks: list[TimingBlock] | None,
        audio_format: str,
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
            self._store[render_id] = {
                "audio_path": audio_path,
                "timing_json": timing_json,
                "format": audio_format,
                "created_at": time.time(),
            }
            self._evict()

    def get(self, render_id: str) -> dict | None:
        with self._lock:
            entry = self._store.get(render_id)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self.TTL_SECONDS:
                self._remove(render_id)
                return None
            return entry

    def _evict(self) -> None:
        now = time.time()
        expired = [
            rid
            for rid, e in self._store.items()
            if now - e["created_at"] > self.TTL_SECONDS
        ]
        for rid in expired:
            self._remove(rid)

        if len(self._store) > self.MAX_ENTRIES:
            by_age = sorted(self._store.items(), key=lambda x: x[1]["created_at"])
            excess = len(self._store) - self.MAX_ENTRIES
            for rid, _ in by_age[:excess]:
                self._remove(rid)

    def _remove(self, render_id: str) -> None:
        entry = self._store.pop(render_id, None)
        if entry is None:
            return
        audio_path = entry.get("audio_path")
        if audio_path and isinstance(audio_path, Path) and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass


render_store = RenderStore()


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

    @app.route("/render", methods=["POST"])
    def render():  # type: ignore[no-untyped-def]
        # Get script text from textarea or uploaded file
        script_text = request.form.get("script", "").strip()
        uploaded = request.files.get("script_file")
        if uploaded and uploaded.filename:
            script_text = uploaded.read().decode("utf-8", errors="replace").strip()

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

        # Create temp output file
        suffix = f".{output_format}"
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="df_render_"
        )
        tmp.close()
        output_path = Path(tmp.name)

        try:
            piper = PiperTTSBackend(max_text_length=500)
            tts = CachedTTSBackend(piper)
            if not tts.list_voices():
                if output_path.exists():
                    output_path.unlink()
                return (
                    jsonify(
                        {
                            "error": "No voice models installed. Use 'drinkingfountain voices download <voice_id>' to install one."
                        }
                    ),
                    500,
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

            # Run render with timeout. Avoid the executor context manager here:
            # it waits for running work before returning, which would defeat the
            # HTTP timeout response for long renders.
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                service.render_from_string,
                script_text,
                output=str(output_path),
                collect_timing=True,
            )
            executor_shutdown = False
            try:
                result = future.result(timeout=RENDER_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                executor_shutdown = True
                if output_path.exists():
                    output_path.unlink()
                return (
                    jsonify(
                        {
                            "error": f"Render timed out after {RENDER_TIMEOUT_SECONDS} seconds."
                        }
                    ),
                    504,
                )
            finally:
                if not executor_shutdown:
                    executor.shutdown(wait=True)

        except (ValueError, FileNotFoundError, RuntimeError) as e:
            if output_path.exists():
                output_path.unlink()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.exception("Unexpected render error")
            if output_path.exists():
                output_path.unlink()
            return jsonify({"error": f"Render failed: {e}"}), 500

        render_id = uuid.uuid4().hex[:12]
        render_store.put(
            render_id=render_id,
            audio_path=output_path,
            timing_blocks=result.timing_blocks,
            audio_format=output_format,
            title=result.script_title,
            duration=result.duration,
        )

        return jsonify(
            {
                "status": "complete",
                "render_id": render_id,
                "audio_url": f"/audio/{render_id}",
                "timing_url": f"/timing/{render_id}",
                "duration": result.duration,
                "script_title": result.script_title,
            }
        )

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

    @app.route("/timing/<render_id>")
    def timing(render_id: str):  # type: ignore[no-untyped-def]
        entry = render_store.get(render_id)
        if entry is None:
            return jsonify({"error": "Not found or expired"}), 404
        if entry["timing_json"] is None:
            return jsonify({"error": "No timing data available"}), 404
        return jsonify(entry["timing_json"])
