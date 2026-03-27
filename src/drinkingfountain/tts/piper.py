"""Piper TTS backend implementation."""

import io
import logging
import subprocess
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Final

from drinkingfountain.utils.text_chunker import TextChunker

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

    def __init__(
        self, voices_dir: Path | None = None, max_text_length: int = 500
    ) -> None:
        """Initialize the Piper TTS backend.

        Args:
            voices_dir: Directory containing voice model files (.onnx). If None,
                       uses the default Piper voices directory.
            max_text_length: Maximum text length before chunking. Texts longer than
                           this will be split into chunks. Default is 500 characters.
        """
        self.voices_dir = (voices_dir or DEFAULT_VOICES_DIR).resolve()
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._voice_cache: dict[str, PiperVoice] = {}
        self._cached_voice_list: list[str] | None = None
        self.max_text_length = max_text_length
        self._chunker = TextChunker(max_chunk_size=max_text_length)

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
                    "--download-dir",
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

        Note:
            If the text exceeds max_text_length, it will be automatically
            chunked and the resulting audio segments will be concatenated
            with a 100ms pause between chunks for natural-sounding speech.
        """
        if not text.strip():
            # Return empty audio? Or raise? For now, return 0-length segment.
            from pydub import AudioSegment

            return AudioSegment.empty()

        # Check if text needs chunking
        if len(text) > self.max_text_length:
            chunks = self._chunker.chunk(text)
            logger.debug(
                "Text length %d exceeds max %d, chunking into %d pieces",
                len(text),
                self.max_text_length,
                len(chunks),
            )

            if not chunks:
                logger.warning(
                    "Chunking produced no chunks, falling back to empty audio"
                )
                from pydub import AudioSegment

                return AudioSegment.empty()

            # Generate audio for each chunk
            from pydub import AudioSegment

            audio_segments: list[AudioSegment] = []
            for i, chunk_text in enumerate(chunks):
                logger.debug(
                    "Synthesizing chunk %d/%d (len=%d): %r...",
                    i + 1,
                    len(chunks),
                    len(chunk_text),
                    chunk_text[:50],
                )
                chunk_audio = self._synthesize_single(chunk_text, voice)
                audio_segments.append(chunk_audio)

            # Concatenate with 100ms pause between chunks
            if len(audio_segments) == 1:
                return audio_segments[0]

            pause = AudioSegment.silent(duration=100)  # 100ms pause
            combined = audio_segments[0]
            for segment in audio_segments[1:]:
                combined = combined + pause + segment

            logger.debug(
                "Combined %d chunks into final audio (duration=%dms)",
                len(audio_segments),
                len(combined),
            )
            return combined
        else:
            # Short text, no chunking needed
            return self._synthesize_single(text, voice)

    def _synthesize_single(self, text: str, voice: str) -> "AudioSegment":
        """Synthesize a single piece of text (assumed to be within length limits).

        Args:
            text: The text to synthesize.
            voice: The voice identifier.

        Returns:
            An AudioSegment containing the synthesized speech.

        Raises:
            FileNotFoundError: If the voice model file is missing.
            RuntimeError: If synthesis fails.
        """
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
