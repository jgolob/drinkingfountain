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

# Try to import pydub to check availability
try:
    import pydub  # noqa: F401
except ImportError:
    # pydub not available, create a mock to allow tests to run
    pydub_mock = ModuleType("pydub")
    audio_segment_mock = MagicMock()
    audio_segment_mock.from_file = MagicMock()
    audio_segment_mock.empty = MagicMock(return_value=MagicMock(duration_seconds=0))
    pydub_mock.AudioSegment = audio_segment_mock  # type: ignore
    sys.modules["pydub"] = pydub_mock


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
                "--download-dir",
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

    def test_generate_audio_with_chunking(self, tmp_path: Path) -> None:
        """Test that long text is chunked and synthesized in pieces."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model content")

        # Create a backend with a small max_text_length to force chunking
        backend = PiperTTSBackend(voices_dir=voices_dir, max_text_length=50)

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
        ):
            # Create a long text (> 50 chars) that will be chunked
            long_text = (
                "This is a very long text that exceeds the maximum chunk size and should be split into multiple pieces for synthesis. "
                * 2
            )
            assert len(long_text) > 50

            # Create enough mock audios for all chunks (use same mock for all)
            mock_audio = make_mock_audio_segment(100)

            with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
                result = backend.generate_audio(long_text, "test_voice")

                # Should synthesize multiple times (once per chunk)
                assert mock_voice.synthesize_wav.call_count > 1

                # The result should be a combined AudioSegment (mocked)
                assert result is not None

    def test_generate_audio_chunks_with_pause(self, tmp_path: Path) -> None:
        """Test that chunks are concatenated with a 100ms pause."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model content")

        backend = PiperTTSBackend(voices_dir=voices_dir, max_text_length=50)

        mock_voice = MagicMock()

        def synthesize_side_effect(text: str, wav_file) -> None:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(b"\x00\x00" * 100)

        mock_voice.synthesize_wav.side_effect = synthesize_side_effect
        with patch(
            "drinkingfountain.tts.piper.PiperVoice.load", return_value=mock_voice
        ):
            # Text that will be chunked (needs to be > 50 chars)
            text = "First chunk content that is long enough. Second chunk content that is also long enough to require splitting."
            # Ensure it's > 50 chars
            assert len(text) > 50

            mock_audio = make_mock_audio_segment(100)

            with patch(
                "pydub.AudioSegment.from_file", return_value=mock_audio
            ) as mock_from_file:
                with patch(
                    "pydub.AudioSegment.silent",
                    return_value=make_mock_audio_segment(100),
                ) as mock_silent:
                    backend.generate_audio(text, "test_voice")

                    # Should have called from_file multiple times (once per chunk)
                    # The exact number depends on the chunking algorithm
                    assert mock_from_file.call_count > 1

                    # Should have created a silent pause (only if more than 1 chunk)
                    if mock_voice.synthesize_wav.call_count > 1:
                        mock_silent.assert_called_once_with(duration=100)

                    # The result should be the combination (we can't easily test the exact
                    # concatenation without a real AudioSegment, but we can verify the
                    # synthesis was called multiple times)
                    assert mock_voice.synthesize_wav.call_count > 1

    def test_generate_audio_short_text_no_chunking(self, tmp_path: Path) -> None:
        """Test that short text (<= max_text_length) does not trigger chunking."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model content")

        backend = PiperTTSBackend(voices_dir=voices_dir, max_text_length=500)

        mock_voice = MagicMock()

        def synthesize_side_effect(text: str, wav_file) -> None:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(b"\x00\x00" * 100)

        mock_voice.synthesize_wav.side_effect = synthesize_side_effect
        with patch(
            "drinkingfountain.tts.piper.PiperVoice.load", return_value=mock_voice
        ):
            with patch(
                "pydub.AudioSegment.from_file",
                return_value=make_mock_audio_segment(100),
            ):
                short_text = "This is short."
                backend.generate_audio(short_text, "test_voice")

                # Should synthesize only once
                mock_voice.synthesize_wav.assert_called_once()
                # The text should be the original short text
                args = mock_voice.synthesize_wav.call_args[0]
                assert args[0] == short_text

    def test_max_text_length_parameter(self, tmp_path: Path) -> None:
        """Test that max_text_length parameter is respected."""
        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        voice_file = voices_dir / "test_voice.onnx"
        voice_file.write_text("fake model content")

        # Test default value
        backend1 = PiperTTSBackend(voices_dir=voices_dir)
        assert backend1.max_text_length == 500
        assert backend1._chunker.max_chunk_size == 500

        # Test custom value
        backend2 = PiperTTSBackend(voices_dir=voices_dir, max_text_length=1000)
        assert backend2.max_text_length == 1000
        assert backend2._chunker.max_chunk_size == 1000

    @patch("subprocess.run")
    def test_list_available_voices_returns_sorted_list(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test list_available_voices returns sorted voice IDs from subprocess output."""
        # Simulate piper.download_voices output
        mock_output = """en_US-amy-medium (en_US, medium, libritts)
en_US-john-medium (en_US, medium, libritts)
fr_FR-henri-medium (fr_FR, medium, libritts)
"""
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

        backend = PiperTTSBackend()
        result = backend.list_available_voices()
        assert result == ["en_US-amy-medium", "en_US-john-medium", "fr_FR-henri-medium"]
        # Verify subprocess was called correctly
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "piper.download_voices"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_list_available_voices_raises_if_piper_not_available(self) -> None:
        """Test list_available_voices raises RuntimeError if Piper not installed."""
        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": False}
        ):
            backend = PiperTTSBackend()
            with pytest.raises(RuntimeError, match="Piper TTS is not installed"):
                backend.list_available_voices()

    @patch("subprocess.run")
    def test_list_available_voices_handles_subprocess_failure(
        self, mock_run: MagicMock
    ) -> None:
        """Test list_available_voices handles subprocess errors."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="download error"
        )

        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": True}
        ):
            backend = PiperTTSBackend()
            with pytest.raises(RuntimeError, match="Failed to fetch available voices"):
                backend.list_available_voices()

    @patch("subprocess.run")
    def test_list_available_voices_handles_empty_output(
        self, mock_run: MagicMock
    ) -> None:
        """Test list_available_voices handles empty output."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict(
            "drinkingfountain.tts.piper.__dict__", {"PIPER_AVAILABLE": True}
        ):
            backend = PiperTTSBackend()
            result = backend.list_available_voices()
            assert result == []


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

    def test_get_voice_for_character_caches_auto_assignment(self) -> None:
        """Test that auto-assigned voice is cached for the character."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1", "voice2"]
        manager = VoiceManager(mock_backend)
        manager.start_render()  # Start fresh render

        # First call should pick and cache
        voice1 = manager.get_voice_for_character("Charlie")
        assert voice1 in {"voice1", "voice2"}

        # Second call should return same cached voice
        voice2 = manager.get_voice_for_character("Charlie")
        assert voice2 == voice1

    def test_start_render_clears_cache(self) -> None:
        """Test that start_render() resets character voice cache."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1", "voice2"]
        manager = VoiceManager(mock_backend)
        manager.start_render()

        # Assign a voice
        manager.get_voice_for_character("Alice")
        assert "Alice" in manager._char_voice_cache

        # New render clears cache
        manager.start_render()
        assert manager._char_voice_cache == {}
        # Should be able to assign different voice (though random)
        v2 = manager.get_voice_for_character("Alice")
        # Could be same or different, but cache is fresh
        assert v2 in {"voice1", "voice2"}

    def test_narrator_voice_excluded_from_auto_pool(self) -> None:
        """Test that narrator voice is not in auto-assignment pool."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["v1", "narrator_voice", "v2"]
        manager = VoiceManager(mock_backend)
        manager.start_render()
        manager.set_narrator_voice("narrator_voice")

        # Auto-assign should pick from v1 or v2 only
        voice = manager.get_voice_for_character("Bob")
        assert voice in {"v1", "v2"}
        assert voice != "narrator_voice"

    def test_narrator_exclusion_raises_if_pool_empty(self) -> None:
        """Test that ValueError raised if all voices are excluded."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["narrator_only"]
        manager = VoiceManager(mock_backend)
        manager.start_render()
        manager.set_narrator_voice("narrator_only")

        with pytest.raises(
            ValueError, match="No voices available for character assignment"
        ):
            manager.get_voice_for_character("Anyone")

    def test_override_can_use_narrator_voice(self) -> None:
        """Test that overrides can still use narrator voice (explicit choice)."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["v1", "narrator_voice"]
        manager = VoiceManager(mock_backend)
        manager.start_render()
        manager.set_narrator_voice("narrator_voice")
        manager.set_character_voice("Alice", "narrator_voice")  # Explicit override

        # Should use narrator voice despite exclusion
        assert manager.get_voice_for_character("Alice") == "narrator_voice"

    def test_download_voice_clears_character_cache(self) -> None:
        """Test that download_voice clears both auto pool and character cache."""
        mock_backend = MagicMock(spec=TTSBackend)
        mock_backend.list_voices.return_value = ["voice1"]
        manager = VoiceManager(mock_backend)
        manager.start_render()

        # Populate auto pool and character cache
        _ = manager.get_voice_for_character("Anyone")
        assert manager._auto_pool == ["voice1"]
        assert "Anyone" in manager._char_voice_cache

        manager.download_voice("new_voice")
        mock_backend.download_voice.assert_called_once_with("new_voice")
        assert manager._auto_pool == []
        assert manager._char_voice_cache == {}
