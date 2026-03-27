"""Persistent disk cache for TTS audio output."""

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .base import TTSBackend

if TYPE_CHECKING:
    from pydub import AudioSegment

logger = logging.getLogger(__name__)


class CachedTTSBackend(TTSBackend):
    """Wrapper that adds persistent disk caching to a TTS backend.

    Audio for each (text, voice) pair is cached in a directory structure.
    Cache key is SHA256 hash of "text|voice".
    """

    def __init__(self, backend: TTSBackend, cache_dir: Path | None = None) -> None:
        """Initialize the cache wrapper.

        Args:
            backend: The underlying TTS backend to wrap.
            cache_dir: Directory to store cached audio files. If None,
                      uses ~/.cache/drinkingfountain/tts.
        """
        self.backend = backend
        self.cache_dir = Path(
            cache_dir or Path.home() / ".cache" / "drinkingfountain" / "tts"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, text: str, voice: str) -> str:
        """Compute a unique cache key for a text/voice pair."""
        key_str = f"{text}|{voice}"
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    def _cached_path(self, key: str) -> Path:
        """Get the file path for a cache key.

        Uses first two characters of key as subdirectory to avoid too many
        files in a single directory.
        """
        return self.cache_dir / key[:2] / f"{key}.wav"

    def generate_audio(self, text: str, voice: str) -> "AudioSegment":
        """Generate audio, using cache if available and valid.

        Args:
            text: Text to synthesize.
            voice: Voice identifier.

        Returns:
            AudioSegment with synthesized speech.
        """
        cache_path = self._cached_path(self._cache_key(text, voice))
        if cache_path.exists():
            try:
                logger.debug("Cache hit for text (len=%d) voice=%s", len(text), voice)
                # Import AudioSegment only when needed to avoid runtime import issues
                from pydub import AudioSegment

                return AudioSegment.from_file(cache_path, format="wav")
            except Exception as e:
                logger.warning("Failed to load cached audio from %s: %s", cache_path, e)
                # Fall through to regenerate

        logger.debug("Cache miss for text (len=%d) voice=%s", len(text), voice)
        # Generate fresh audio
        audio = self.backend.generate_audio(text, voice)
        # Save to cache
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            audio.export(cache_path, format="wav")
            logger.debug("Cached audio to %s", cache_path)
        except Exception as e:
            logger.warning("Failed to write cache to %s: %s", cache_path, e)

        return audio

    def list_voices(self) -> list[str]:
        """List available voices (delegated to backend)."""
        return self.backend.list_voices()

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        """Download a voice model (delegated to backend).

        Also clears the auto-assignment pool cache in VoiceManager? Not here.
        """
        self.backend.download_voice(voice, target_dir)

    def is_available(self) -> bool:
        """Check if the underlying backend is available."""
        return self.backend.is_available()
