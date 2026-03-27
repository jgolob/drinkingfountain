"""Tests for TTS backends and voice management."""

import io
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from drinkingfountain.tts.base import TTSBackend
from drinkingfountain.tts.cache import CachedTTSBackend
from drinkingfountain.tts.piper import PiperTTSBackend
from drinkingfountain.voices.manager import VoiceManager

# Mock pydub if it's not available due to missing audioop (common in some Python builds)
if "pydub" not in sys.modules:
    pydub_mock = ModuleType("pydub")
    audio_segment_mock = MagicMock()
    audio_segment_mock.from_file = MagicMock()
    audio_segment_mock.empty = MagicMock(return_value=MagicMock(duration_seconds=0))
    pydub_mock.AudioSegment = audio_segment_mock  # type: ignore  # Injecting mock attribute into test double module
    sys.modules["pydub"] = pydub_mock
else:
    # pydub is available, but we still want to control its behavior in tests
    # We'll patch specific methods as needed in each test
    pass


# Helper: create a mock AudioSegment
def make_mock_audio_segment(duration_ms: int = 100) -> MagicMock:
    """Create a mock AudioSegment with a specified duration."""
    audio = MagicMock()
    audio.duration_seconds = duration_ms / 1000.0
    # Mock export method
    audio.export = MagicMock()
    return audio


class TestPiperTTSBackend:
    """Tests for the Piper TTS backend."""

    def test_is_available_returns_module_flag(self) -> None:
        """Test is_available returns the PIPER_AVAILABLE module flag."""
        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": True}
        ):
            backend = PiperTTSBackend()
            assert backend.is_available() is True
        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": False}
        ):
            backend = PiperTTSBackend()
            assert backend.is_available() is False

    def test_list_voices_scans_onnx_files(self, tmp_path: Path) -> None:
        """Test list_voices returns .onnx file stems from voices directory."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        (voices_dir / "en_US-amy-medium.onnx").touch()
        (voices_dir / "en_US-john-medium.onnx").touch()
        (voices_dir / "notes.txt").touch()

        backend = PiperTTSBackend(voices_dir=voices_dir)
        voices = backend.list_voices()
        assert set(voices) == {"en_US-amy-medium", "en_US-john-medium"}

    def test_list_voices_returns_empty_if_dir_missing(self, tmp_path: Path) -> None:
        """Test list_voices returns empty list when voices_dir does not exist."""
        backend = PiperTTSBackend(voices_dir=tmp_path / "nonexistent")
        voices = backend.list_voices()
        assert voices == []

    def test_download_voice_uses_subprocess(self, tmp_path: Path) -> None:
        """Test download_voice calls subprocess.run with correct arguments."""
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        backend = PiperTTSBackend()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            backend.download_voice("en_US-amy-medium", target_dir=download_dir)
            expected_cmd = [
                sys.executable,
                "-m",
                "piper.download_voices",
                "en_US-amy-medium",
                "--dest",
                str(download_dir),
            ]
            mock_run.assert_called_once_with(
                expected_cmd, check=True, capture_output=True, text=True
            )

    def test_download_voice_raises_on_subprocess_failure(self, tmp_path: Path) -> None:
        """Test download_voice raises RuntimeError if subprocess fails."""
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        backend = PiperTTSBackend()
        mock_run = MagicMock(
            side_effect=subprocess.CalledProcessError(1, "cmd", stderr="download error")
        )
        with patch("subprocess.run", mock_run):
            with pytest.raises(RuntimeError, match="Voice download failed"):
                backend.download_voice("en_US-amy-medium", target_dir=download_dir)

    def test_download_voice_raises_if_piper_not_available(self) -> None:
        """Test download_voice raises if Piper is not installed."""
        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": False}
        ):
            backend = PiperTTSBackend()
            with pytest.raises(RuntimeError, match="Piper TTS is not installed"):
                backend.download_voice("en_US-amy-medium")

    def test_generate_audio_loads_voice_and_synthesizes(self, tmp_path: Path) -> None:
        """Test generate_audio loads voice and returns AudioSegment."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model content")

        backend = PiperTTSBackend(voices_dir=voices_dir)
        mock_voice = MagicMock()

        def synthesize_side_effect(text: str, wav_file) -> None:
            """Simulate writing WAV data to the wave file."""
            # Set required WAV parameters
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            # Write some silent frames
            wav_file.writeframes(b"\x00\x00" * 100)

        mock_voice.synthesize_wav.side_effect = synthesize_side_effect
        with patch(
            "drinkingfountain.tts.piper.PiperVoice.load", return_value=mock_voice
        ):
            mock_audio = make_mock_audio_segment(100)
            with patch(
                "pydub.AudioSegment.from_file", return_value=mock_audio
            ) as mock_from_file:
                result = backend.generate_audio("Hello world", "test_voice")
                assert result is mock_audio
                mock_voice.synthesize_wav.assert_called_once()
                args = mock_voice.synthesize_wav.call_args[0]
                assert args[0] == "Hello world"
                # The second arg should be a Wave_write (has setnchannels, writeframes)
                wav_file_arg = args[1]
                assert hasattr(wav_file_arg, "setnchannels")
                assert hasattr(wav_file_arg, "writeframes")
                # Verify from_file was called with a BytesIO (the buffer)
                mock_from_file.assert_called_once()
                file_arg = mock_from_file.call_args[0][0]
                assert isinstance(file_arg, io.BytesIO)

    def test_generate_audio_returns_empty_for_blank_text(self, tmp_path: Path) -> None:
        """Test generate_audio returns an empty AudioSegment for empty/whitespace text."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model")

        backend = PiperTTSBackend(voices_dir=voices_dir)
        # No need to mock voice loading because empty text short-circuits before loading
        mock_empty = make_mock_audio_segment(0)
        with patch(
            "pydub.AudioSegment.empty", return_value=mock_empty
        ) as mock_empty_func:
            audio = backend.generate_audio("   \n  ", "test_voice")
            assert audio is mock_empty
            mock_empty_func.assert_called_once()

    def test_generate_audio_raises_if_voice_missing(self, tmp_path: Path) -> None:
        """Test generate_audio raises FileNotFoundError if voice model file not found."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        # No voice file created
        backend = PiperTTSBackend(voices_dir=voices_dir)
        with pytest.raises(FileNotFoundError, match="Voice model not found"):
            backend.generate_audio("Hello", "unknown_voice")

    def test_generate_audio_caches_voice_object(self, tmp_path: Path) -> None:
        """Test that voice objects are cached after first load."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "cached_voice.onnx"
        voice_file.write_text("fake model")

        backend = PiperTTSBackend(voices_dir=voices_dir)
        # Ensure cache is empty
        assert backend._voice_cache == {}

        mock_voice = MagicMock()

        def synthesize_side_effect(text: str, wav_file) -> None:
            """Simulate writing WAV data to the wave file."""
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(b"\x00\x00" * 100)

        mock_voice.synthesize_wav.side_effect = synthesize_side_effect
        with patch(
            "drinkingfountain.tts.piper.PiperVoice.load", return_value=mock_voice
        ) as mock_load:
            with patch(
                "pydub.AudioSegment.from_file",
                return_value=make_mock_audio_segment(100),
            ):
                # First call loads the voice
                backend.generate_audio("First", "cached_voice")
                assert "cached_voice" in backend._voice_cache
                assert backend._voice_cache["cached_voice"] is mock_voice
                assert mock_load.call_count == 1
                # Second call should use cached voice, not call load again
                backend.generate_audio("Second", "cached_voice")
                assert mock_load.call_count == 1  # Still 1


class TestCachedTTSBackend:
    """Tests for the caching wrapper."""

    def test_cache_hit_returns_cached_audio(self, tmp_path: Path) -> None:
        """Test that a cached audio file is reused."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_backend = MagicMock(spec=TTSBackend)
        mock_audio = make_mock_audio_segment(100)

        cached = CachedTTSBackend(mock_backend, cache_dir=cache_dir)

        # Compute the cache key for the given text and voice
        key = cached._cache_key("Hello", "test_voice")
        cache_subdir = cache_dir / key[:2]
        cache_subdir.mkdir()
        cache_file = cache_subdir / f"{key}.wav"
        cache_file.write_bytes(b"fake wav data")

        # Patch pydub.AudioSegment.from_file to return our mock audio
        with patch(
            "pydub.AudioSegment.from_file", return_value=mock_audio
        ) as mock_from_file:
            audio = cached.generate_audio("Hello", "test_voice")
            assert audio is mock_audio
            mock_from_file.assert_called_once_with(cache_file, format="wav")
            # Backend should not be called on cache hit
            mock_backend.generate_audio.assert_not_called()

    def test_cache_miss_calls_backend_and_saves(self, tmp_path: Path) -> None:
        """Test that a cache miss generates new audio and caches it."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_backend = MagicMock(spec=TTSBackend)
        mock_audio = make_mock_audio_segment(100)
        mock_backend.generate_audio.return_value = mock_audio

        cached = CachedTTSBackend(mock_backend, cache_dir=cache_dir)

        # Simulate cache miss by patching from_file to raise FileNotFoundError
        with patch("pydub.AudioSegment.from_file", side_effect=FileNotFoundError):
            audio = cached.generate_audio("Hello", "test_voice")
            assert audio is mock_audio
            mock_backend.generate_audio.assert_called_once_with("Hello", "test_voice")
            # Check that audio.export was called to write cache
            mock_audio.export.assert_called_once()
            # Verify export was called with a Path and format='wav' keyword
            call_args = mock_audio.export.call_args
            assert isinstance(call_args[0][0], Path)
            assert call_args[1].get("format") == "wav"

    def test_cache_handles_load_errors_gracefully(self, tmp_path: Path) -> None:
        """Test that corrupted cache files fall back to backend."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create a corrupted cache file
        key = "corrupt"
        cache_subdir = cache_dir / key[:2]
        cache_subdir.mkdir()
        cache_file = cache_subdir / f"{key}.wav"
        cache_file.write_bytes(b"corrupted data")

        mock_backend = MagicMock(spec=TTSBackend)
        mock_audio = make_mock_audio_segment(100)
        mock_backend.generate_audio.return_value = mock_audio

        cached = CachedTTSBackend(mock_backend, cache_dir=cache_dir)

        with patch("pydub.AudioSegment.from_file", side_effect=Exception("bad file")):
            audio = cached.generate_audio("Hello", "test_voice")
            assert audio is mock_audio
            mock_backend.generate_audio.assert_called_once()
            # The corrupted file should be overwritten on export
            mock_audio.export.assert_called_once()

    def test_cache_delegates_other_methods(self) -> None:
        """Test list_voices, download_voice, is_available delegate to backend."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1"]
        cached = CachedTTSBackend(mock_backend)

        assert cached.list_voices() == ["voice1"]
        mock_backend.list_voices.assert_called_once()

        cached.download_voice("voice2")
        mock_backend.download_voice.assert_called_once_with("voice2", None)

        mock_backend.is_available.return_value = False
        assert cached.is_available() is False


class TestVoiceManager:
    """Tests for voice assignment and management."""

    def test_get_voice_for_character_uses_override(self) -> None:
        """Test that explicit overrides take precedence."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1", "voice2"]
        manager = VoiceManager(mock_backend)
        manager.set_character_voice("Alice", "voice2")
        assert manager.get_voice_for_character("Alice") == "voice2"

    def test_get_voice_for_character_uses_default_if_no_override(self) -> None:
        """Test that default voice is used when no override."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1", "voice2"]
        manager = VoiceManager(mock_backend)
        manager.set_default_voice("voice1")
        assert manager.get_voice_for_character("Bob") == "voice1"

    def test_get_voice_for_character_auto_assigns_if_no_default(self) -> None:
        """Test random auto-assignment from available pool when no default."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1", "voice2"]
        manager = VoiceManager(mock_backend)
        # Since it's random, we can't assert exact value, but we can check it's one of them
        voice = manager.get_voice_for_character("Charlie")
        assert voice in {"voice1", "voice2"}

    def test_get_voice_for_character_raises_if_no_voices(self) -> None:
        """Test error when no voices are available."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = []
        manager = VoiceManager(mock_backend)
        with pytest.raises(RuntimeError, match="No voices available"):
            manager.get_voice_for_character("Nobody")

    def test_download_voice_delegates_and_clears_cache(self) -> None:
        """Test download_voice calls backend and resets auto pool."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1"]
        manager = VoiceManager(mock_backend)
        # Populate auto pool
        _ = manager.get_voice_for_character("Anyone")  # Fills _auto_pool
        assert manager._auto_pool == ["voice1"]
        manager.download_voice("new_voice")
        mock_backend.download_voice.assert_called_once_with("new_voice")
        assert manager._auto_pool == []  # Cache cleared

    def test_clear_overrides_removes_all(self) -> None:
        """Test clear_overrides removes all character overrides."""
        mock_backend = MagicMock(spec=TTSBackend)
        manager = VoiceManager(mock_backend)
        manager.set_character_voice("Alice", "v1")
        manager.set_character_voice("Bob", "v2")
        assert len(manager.get_overrides()) == 2
        manager.clear_overrides()
        assert manager.get_overrides() == {}

    def test_get_overrides_returns_copy(self) -> None:
        """Test get_overrides returns a copy, not the internal dict."""
        mock_backend = MagicMock(spec=TTSBackend)
        manager = VoiceManager(mock_backend)
        manager.set_character_voice("Alice", "v1")
        overrides = manager.get_overrides()
        overrides["Bob"] = "v2"  # Modify copy
        assert "Bob" not in manager.get_overrides()
