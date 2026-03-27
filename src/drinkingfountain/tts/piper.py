"""Piper TTS backend implementation."""

import io
import logging
import subprocess
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .base import TTSBackend

if TYPE_CHECKING:
    from pydub import AudioSegment

# Try to import piper modules; may raise ImportError if not available
try:
    from piper import PiperVoice

    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default Piper voices directory
DEFAULT_VOICES_DIR: Final[Path] = (
    Path.home() / ".local" / "share" / "piper-tts" / "voices"
)


class PiperTTSBackend(TTSBackend):
    """Piper TTS backend using local voice models.

    This backend uses the piper-tts library to synthesize speech locally.
    Voice models are stored in a directory and loaded on demand with caching.
    """

    def __init__(self, voices_dir: Path | None = None) -> None:
        """Initialize the Piper TTS backend.

        Args:
            voices_dir: Directory containing voice model files (.onnx). If None,
                       uses the default Piper voices directory.
        """
        self.voices_dir = (voices_dir or DEFAULT_VOICES_DIR).resolve()
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._voice_cache: dict[str, PiperVoice] = {}
        self._cached_voice_list: list[str] | None = None

    def is_available(self) -> bool:
        """Check if Piper TTS is installed and importable."""
        return PIPER_AVAILABLE

    def list_voices(self) -> list[str]:
        """List installed voice models found in the voices directory.

        Returns:
            A list of voice identifiers (the stem of the .onnx file).
        """
        if self._cached_voice_list is not None:
            return self._cached_voice_list

        if not self.voices_dir.exists():
            return []

        voices = []
        for path in self.voices_dir.iterdir():
            if path.suffix == ".onnx":
                voices.append(path.stem)
        self._cached_voice_list = voices
        return voices

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        """Download a voice model.

        Args:
            voice: The voice identifier to download.
            target_dir: Optional custom download directory. If None, uses
                       the backend's voices_dir.

        Raises:
            RuntimeError: If the download fails or Piper is not installed.
        """
        if not PIPER_AVAILABLE:
            raise RuntimeError("Piper TTS is not installed. Cannot download voices.")

        download_dir = target_dir or self.voices_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Use subprocess to call piper's download_voices module
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "piper.download_voices",
                    voice,
                    "--dest",
                    str(download_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Downloaded voice '%s' to %s", voice, download_dir)
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to download voice '%s': exit code %d, stderr: %s",
                voice,
                e.returncode,
                e.stderr,
            )
            raise RuntimeError(f"Voice download failed: {e.stderr}") from e
        except Exception as e:
            logger.error("Failed to download voice '%s': %s", voice, e)
            raise RuntimeError(f"Voice download failed: {e}") from e

    def _load_voice(self, voice: str) -> PiperVoice:
        """Load a voice model from disk, with caching."""
        if voice in self._voice_cache:
            return self._voice_cache[voice]

        voice_path = self.voices_dir / f"{voice}.onnx"
        if not voice_path.exists():
            raise FileNotFoundError(
                f"Voice model not found: {voice_path}. "
                f"Use 'drinkingfountain voices download {voice}' to download it."
            )

        try:
            voice_obj = PiperVoice.load(voice_path)
            self._voice_cache[voice] = voice_obj
            return voice_obj
        except Exception as e:
            logger.error("Failed to load voice model '%s': %s", voice, e)
            raise RuntimeError(f"Voice loading failed: {e}") from e

    def generate_audio(self, text: str, voice: str) -> "AudioSegment":
        """Synthesize text to audio using the specified Piper voice.

        Args:
            text: The text to synthesize. Should be plain text; any SSML
                  or special markup should be handled by the caller.
            voice: The voice identifier (e.g., "en_US-amy-medium").

        Returns:
            An AudioSegment containing the synthesized speech.

        Raises:
            FileNotFoundError: If the voice model file is missing.
            RuntimeError: If synthesis fails.
        """
        if not text.strip():
            # Return empty audio? Or raise? For now, return 0-length segment.
            from pydub import AudioSegment

            return AudioSegment.empty()

        voice_obj = self._load_voice(voice)

        try:
            # Synthesize to an in-memory WAV file using wave.open to get a proper Wave_write
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                voice_obj.synthesize_wav(text, wav_file)
            wav_buffer.seek(0)

            # Load into AudioSegment
            from pydub import AudioSegment

            return AudioSegment.from_file(wav_buffer, format="wav")
        except Exception as e:
            logger.error("TTS synthesis failed for voice '%s': %s", voice, e)
            raise RuntimeError(f"Synthesis failed: {e}") from e
