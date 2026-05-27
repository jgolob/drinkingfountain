"""Tests for the Flask web interface."""

from io import BytesIO
from pathlib import Path

import pytest
from pydub import AudioSegment

from drinkingfountain.services import RenderResult, TimingBlock, TimingMetrics
from drinkingfountain.tts.base import TTSBackend
from drinkingfountain.web import create_app
from drinkingfountain.web.app import RenderStore, build_config_from_form


class FakeTTSBackend(TTSBackend):
    """Small fake backend for web route tests."""

    def __init__(
        self, voices: list[str] | None = None, max_text_length: int = 500
    ) -> None:
        self.voices = voices if voices is not None else ["voice1", "voice2"]
        self.max_text_length = max_text_length

    def generate_audio(self, text: str, voice: str) -> AudioSegment:
        return AudioSegment.silent(duration=100, frame_rate=22050)

    def list_voices(self) -> list[str]:
        return self.voices

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        return None

    def is_available(self) -> bool:
        return True


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
        ) -> RenderResult:
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

    monkeypatch.setattr("drinkingfountain.web.app.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.web.app.CachedTTSBackend", lambda piper: piper
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}test{suffix}"),
    )

    response = app.test_client().post(
        "/render",
        data={
            "script": "INT. ROOM - DAY\n\nJOHN\nHello.",
            "narrator_enabled": "",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "complete"
    assert payload["audio_url"].startswith("/audio/")
    assert payload["timing_url"].startswith("/timing/")


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

    monkeypatch.setattr("drinkingfountain.web.app.PiperTTSBackend", FakeTTSBackend)
    monkeypatch.setattr(
        "drinkingfountain.web.app.CachedTTSBackend", lambda piper: piper
    )
    monkeypatch.setattr("drinkingfountain.web.app.RenderService", FakeRenderService)
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(tmp_path / f"{prefix}upload{suffix}"),
    )

    uploaded_script = "INT. UPLOAD - DAY\n\nMARY\nFrom the uploaded file."
    response = app.test_client().post(
        "/render",
        data={
            "script": "",
            "script_file": (
                BytesIO(uploaded_script.encode("utf-8")),
                "uploaded.fountain",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["script_text"] == uploaded_script


def test_render_endpoint_removes_temp_file_when_no_voices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = create_app()
    app.config["TESTING"] = True
    temp_path = tmp_path / "df_render_test.wav"

    monkeypatch.setattr(
        "drinkingfountain.web.app.PiperTTSBackend",
        lambda max_text_length: FakeTTSBackend(voices=[]),
    )
    monkeypatch.setattr(
        "drinkingfountain.web.app.CachedTTSBackend", lambda piper: piper
    )
    monkeypatch.setattr(
        "drinkingfountain.web.app.tempfile.NamedTemporaryFile",
        lambda delete, suffix, prefix: _TempFile(temp_path),
    )

    response = app.test_client().post(
        "/render",
        data={"script": "INT. ROOM - DAY\n\nJOHN\nHello."},
    )

    assert response.status_code == 500
    assert not temp_path.exists()


class _TempFile:
    def __init__(self, path: Path) -> None:
        self.name = str(path)
        path.touch()

    def close(self) -> None:
        return None
