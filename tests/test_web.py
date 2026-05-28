"""Tests for the Flask web interface."""

import socket
import time
from io import BytesIO
from pathlib import Path

import pytest
from pydub import AudioSegment

from drinkingfountain.parser.script import Scene
from drinkingfountain.services import RenderResult, TimingBlock, TimingMetrics
from drinkingfountain.tts.base import TTSBackend
from drinkingfountain.web import create_app, find_available_port
from drinkingfountain.web.app import RenderStore, build_config_from_form, render_store


class FakeTTSBackend(TTSBackend):
    """Small fake backend for web route tests."""

    def __init__(
        self,
        voices: list[str] | None = None,
        max_text_length: int = 500,
        voices_dir: Path | None = None,
    ) -> None:
        self.voices = voices if voices is not None else ["voice1", "voice2"]
        self.max_text_length = max_text_length
        self.voices_dir = voices_dir

    def generate_audio(self, text: str, voice: str) -> AudioSegment:
        return AudioSegment.silent(duration=100, frame_rate=22050)

    def list_voices(self) -> list[str]:
        return self.voices

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        return None

    def is_available(self) -> bool:
        return True


class InlineExecutor:
    """Executor test double that runs submitted work immediately."""

    def submit(self, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)


def test_build_config_from_form_uses_defaults_and_overrides() -> None:
    config = build_config_from_form(
        {
            "sample_rate": "44100",
            "channels": "stereo",
            "pause_between_lines": "0.5",
            "narrator_enabled": "on",
            "expand_int_ext": "on",
            "voice_char_1": "JOHN",
            "voice_id_1": "voice1",
        }
    )

    assert config.audio.sample_rate == 44100
    assert config.audio.channels == "stereo"
    assert config.audio.normalize is True
    assert config.timing.pause_between_lines == 0.5
    assert config.narrator.enabled is True
    assert config.narrator.expand_int_ext is True
    assert config.voices == {"JOHN": "voice1"}


def test_find_available_port_skips_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        occupied_port = sock.getsockname()[1]
        available_port = find_available_port(
            host="127.0.0.1",
            preferred_port=occupied_port,
            search_limit=20,
        )

        assert available_port != occupied_port
        assert occupied_port < available_port < occupied_port + 20


def test_render_store_evicts_audio_file(tmp_path: Path) -> None:
    store = RenderStore()
    store.TTL_SECONDS = 0
    audio_path = tmp_path / "render.wav"
    audio_path.write_bytes(b"RIFF")

    store.put(
        render_id="abc123",
        audio_path=audio_path,
        timing_blocks=None,
        audio_format="wav",
        title="Test",
        duration=1.0,
    )

    assert store.get("abc123") is None
    assert not audio_path.exists()


def test_render_store_expiration_uses_last_update(tmp_path: Path) -> None:
    store = RenderStore()
    store.TTL_SECONDS = 1
    audio_path = tmp_path / "long-render.wav"
    audio_path.write_bytes(b"RIFF")

    store.put_pending(
        render_id="long-render",
        audio_path=audio_path,
        audio_format="wav",
        download_name="long-render.wav",
    )
    store._store["long-render"]["created_at"] = time.time() - 10
    store._store["long-render"]["updated_at"] = time.time()

    assert store.get("long-render") is not None
    assert audio_path.exists()


def test_render_store_does_not_expire_active_render(tmp_path: Path) -> None:
    store = RenderStore()
    store.TTL_SECONDS = 1
    audio_path = tmp_path / "still-running.wav"
    audio_path.write_bytes(b"RIFF")

    store.put_pending(
        render_id="still-running",
        audio_path=audio_path,
        audio_format="wav",
        download_name="still-running.wav",
    )
    store._store["still-running"]["created_at"] = time.time() - 60
    store._store["still-running"]["updated_at"] = time.time() - 60
    store._store["still-running"]["status"] = "running"

    assert store.get("still-running") is not None
    assert audio_path.exists()


def test_render_endpoint_returns_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True

    class FakeRenderService:
        def __init__(
            self,
            config: object,
            tts: object,
            voice_mgr: object,
            narrator_cfg: object,
        ) -> None:
            pass

        def render_from_string(
            self,
            script_text: str,
            output: str,
            collect_timing: bool,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            if progress_callback:
                progress_callback(
                    {
                        "stage": "rendering",
                        "message": "Rendering scene 1/1",
                        "current_scene": 1,
                        "total_scenes": 1,
                        "percent": 95,
                    }
                )
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=1.25,
                tts_calls=1,
                script_title="Untitled",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.01,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[
                    TimingBlock(
                        type="dialogue",
                        text="Hello.",
                        character="JOHN",
                        start=0.0,
                        end=1.25,
                    )
                ],
            )

    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr("drinkingfountain.web.app.RENDER_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}test{suffix}"),
    )

    response = app.test_client().post(
        "/render",
        data={
            "script": "INT. ROOM - DAY\n\nJOHN\nHello.",
            "narrator_enabled": "",
            "create_download": "on",
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "queued"
    progress_response = app.test_client().get(payload["progress_url"])
    progress_payload = progress_response.get_json()
    assert progress_payload is not None
    assert progress_payload["status"] == "complete"
    assert progress_payload["audio_url"].startswith("/audio/")
    assert progress_payload["timing_url"].startswith("/timing/")
    assert progress_payload["download_url"].startswith("/download/")


def test_render_endpoint_uses_uploaded_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    captured: dict[str, str] = {}

    class FakeRenderService:
        def __init__(
            self,
            config: object,
            tts: object,
            voice_mgr: object,
            narrator_cfg: object,
        ) -> None:
            pass

        def render_from_string(
            self,
            script_text: str,
            output: str,
            collect_timing: bool,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            captured["script_text"] = script_text
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=0.5,
                tts_calls=1,
                script_title="Uploaded",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.01,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[],
            )

    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr("drinkingfountain.web.app.RENDER_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}upload{suffix}"),
    )

    uploaded_script = "INT. UPLOAD - DAY\n\nMARY\nFrom the uploaded file."
    response = app.test_client().post(
        "/render",
        data={
            "script": "",
            "create_download": "on",
            "script_file": (
                BytesIO(uploaded_script.encode("utf-8")),
                "uploaded.fountain",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    assert captured["script_text"] == uploaded_script


def test_render_endpoint_prefers_textarea_over_uploaded_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    captured: dict[str, str] = {}

    class FakeRenderService:
        def __init__(
            self,
            config: object,
            tts: object,
            voice_mgr: object,
            narrator_cfg: object,
        ) -> None:
            pass

        def render_from_string(
            self,
            script_text: str,
            output: str,
            collect_timing: bool,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            captured["script_text"] = script_text
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=0.5,
                tts_calls=1,
                script_title="Edited",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.01,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[],
            )

    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr("drinkingfountain.web.app.RENDER_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}edited{suffix}"),
    )

    edited_script = "INT. EDITED - DAY\n\nJOHN\nUse the text box."
    uploaded_script = "INT. UPLOAD - DAY\n\nMARY\nUse the stale upload."
    response = app.test_client().post(
        "/render",
        data={
            "script": edited_script,
            "create_download": "on",
            "script_file": (
                BytesIO(uploaded_script.encode("utf-8")),
                "uploaded.fountain",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    assert captured["script_text"] == edited_script


def test_live_preview_endpoint_returns_scene_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True

    class FakeRenderService:
        def __init__(
            self,
            config: object,
            tts: object,
            voice_mgr: object,
            narrator_cfg: object,
        ) -> None:
            pass

        def render_from_string(
            self,
            script_text: str,
            output: str,
            collect_timing: bool,
            title: str | None = None,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=0.5,
                tts_calls=1,
                script_title=title or "Live",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.01,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[
                    TimingBlock(
                        type="dialogue",
                        text="Hello.",
                        character="JOHN",
                        start=0.0,
                        end=0.5,
                    )
                ],
            )

        def render_scene(
            self,
            scene: Scene,
            output: str,
            collect_timing: bool,
            title: str | None = None,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=0.5,
                tts_calls=1,
                script_title=title or "Live",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.0,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[
                    TimingBlock(
                        type="dialogue",
                        text="Hello.",
                        character="JOHN",
                        start=0.0,
                        end=0.5,
                    )
                ],
            )

    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr("drinkingfountain.web.app.LIVE_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}live{suffix}"),
    )

    response = app.test_client().post(
        "/render",
        data={
            "script": "INT. ONE - DAY\n\nJOHN\nHello.\n\nINT. TWO - DAY\n\nMARY\nHi.",
            "live_preview": "on",
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload is not None
    assert payload["mode"] == "live"
    state_response = app.test_client().get(payload["progress_url"])
    state_payload = state_response.get_json()
    assert state_payload is not None
    assert state_payload["status"] == "complete"
    assert sorted(state_payload["ready_scenes"]) == ["0", "1"]
    audio_response = app.test_client().get(
        state_payload["ready_scenes"]["0"]["audio_url"]
    )
    assert audio_response.status_code == 200


def test_live_preview_skips_title_page_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    rendered_headings: list[str] = []

    class FakeRenderService:
        def __init__(
            self,
            config: object,
            tts: object,
            voice_mgr: object,
            narrator_cfg: object,
        ) -> None:
            pass

        def render_scene(
            self,
            scene: Scene,
            output: str,
            collect_timing: bool,
            title: str | None = None,
            progress_callback=None,
            control_callback=None,
        ) -> RenderResult:
            rendered_headings.append(scene.heading.content)
            Path(output).write_bytes(b"RIFF")
            return RenderResult(
                duration=0.5,
                tts_calls=1,
                script_title=title or "Live",
                scene_count=1,
                character_count=1,
                dialogue_count=1,
                timing=TimingMetrics(
                    total_wall=0.1,
                    parse_time=0.01,
                    tts_time=0.02,
                    tts_calls=1,
                    output_time=0.03,
                ),
                output_path=Path(output),
                timing_blocks=[
                    TimingBlock(
                        type="dialogue",
                        text="Welcome.",
                        character="CLAIRE",
                        start=0.0,
                        end=0.5,
                    )
                ],
            )

    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr("drinkingfountain.web.app.LIVE_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}live{suffix}"),
    )

    response = app.test_client().post(
        "/render",
        data={
            "script": (
                "Title: FISSION EPISODE 101\n"
                "Author: Jonathan Golob\n\n"
                "# ACT I\n\n"
                ".INT. FUKUSHIMA DAIICHI - DAY\n\n"
                "CLAIRE\n"
                "Welcome.\n"
            ),
            "live_preview": "on",
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload is not None
    assert payload["scenes"] == [
        {
            "index": 0,
            "source_scene_index": 0,
            "heading": "INT. FUKUSHIMA DAIICHI - DAY",
            "line_number": 6,
        }
    ]
    assert rendered_headings == ["INT. FUKUSHIMA DAIICHI - DAY"]


def test_script_info_uses_parser_and_voice_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    monkeypatch.setattr("drinkingfountain.tts.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.voices.manager.random.choice",
        lambda voices: voices[0],
    )

    response = app.test_client().post(
        "/api/script-info",
        data={
            "script": "INT. ROOM - DAY\n\nJOHN\nHello.\n\nMARY\nHi.",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["characters"] == ["JOHN", "MARY"]
    assert payload["scene_count"] == 1
    assert payload["voices"] == ["voice1", "voice2"]
    assert payload["assignments"] == {"JOHN": "voice1", "MARY": "voice1"}


def test_script_info_rejects_empty_script() -> None:
    app = create_app()
    app.config["TESTING"] = True

    response = app.test_client().post("/api/script-info", data={"script": ""})

    assert response.status_code == 400
    assert response.get_json() == {"error": "No script provided."}


def test_render_control_endpoints(tmp_path: Path) -> None:
    app = create_app()
    app.config["TESTING"] = True
    render_id = "control-test"
    audio_path = tmp_path / "control.wav"
    audio_path.write_bytes(b"RIFF")
    render_store.put_pending(
        render_id=render_id,
        audio_path=audio_path,
        audio_format="wav",
        download_name="control.wav",
    )

    client = app.test_client()
    pause_response = client.post(f"/pause/{render_id}")
    assert pause_response.status_code == 200
    progress_response = client.get(f"/progress/{render_id}")
    progress_payload = progress_response.get_json()
    assert progress_payload is not None
    assert progress_payload["status"] == "paused"

    resume_response = client.post(f"/resume/{render_id}")
    assert resume_response.status_code == 200
    progress_response = client.get(f"/progress/{render_id}")
    progress_payload = progress_response.get_json()
    assert progress_payload is not None
    assert progress_payload["status"] == "running"

    cancel_response = client.post(f"/cancel/{render_id}")
    assert cancel_response.status_code == 200
    progress_response = client.get(f"/progress/{render_id}")
    progress_payload = progress_response.get_json()
    assert progress_payload is not None
    assert progress_payload["status"] == "cancelling"


def test_render_endpoint_removes_temp_file_when_no_voices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    temp_path = tmp_path / "df_render_test.wav"

    monkeypatch.setattr(
        "drinkingfountain.tts.PiperTTSBackend",
        lambda max_text_length: FakeTTSBackend(voices=[]),
    )
    monkeypatch.setattr(
        "drinkingfountain.tts.CachedTTSBackend",
        lambda piper, cache_dir=None: piper,
    )
    monkeypatch.setattr("drinkingfountain.web.app.RENDER_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(temp_path),
    )

    response = app.test_client().post(
        "/render",
        data={"script": "INT. ROOM - DAY\n\nJOHN\nHello.", "create_download": "on"},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload is not None
    progress_response = app.test_client().get(payload["progress_url"])
    progress_payload = progress_response.get_json()
    assert progress_payload is not None
    assert progress_payload["status"] == "failed"
    assert not temp_path.exists()


class _TempFile:
    def __init__(self, path: Path) -> None:
        self.name = str(path)
        path.touch()

    def close(self) -> None:
        return None
