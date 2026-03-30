"""Piper TTS backend implementation."""

import io
import logging
import subprocess
import sys
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    # Try to import VOICES dictionary from various possible locations
    PIPER_AVAILABLE_VOICES = None
    try:
        from piper.download_voices import (
            VOICES as PIPER_AVAILABLE_VOICES,  # type: ignore
        )
    except (ImportError, AttributeError):
        # Fallback: try alternative import paths
        try:
            from piper.voices import VOICES as PIPER_AVAILABLE_VOICES  # type: ignore
        except (ImportError, AttributeError):
            PIPER_AVAILABLE_VOICES = None
except ImportError:
    PIPER_AVAILABLE = False
    PIPER_AVAILABLE_VOICES = None

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

    def list_available_voices(self) -> list[str]:
        """List voice models available for download from Piper.

        Returns:
            A list of available voice identifiers (e.g., "en_US-amy-medium").
            Returns an empty list if Piper TTS is not installed.

        Raises:
            RuntimeError: If the voice list cannot be retrieved.
        """
        if not PIPER_AVAILABLE:
            raise RuntimeError(
                "Piper TTS is not installed. Cannot fetch available voices.\n"
                "Install with: pip install piper-tts"
            )

        try:
            # Use subprocess to call piper's download_voices module
            # Running without arguments lists all available voices
            result = subprocess.run(
                [sys.executable, "-m", "piper.download_voices"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Parse the output: one voice per line, possibly with extra info
            # The output format is typically: voice_id (language, quality, dataset)
            # We'll extract just the voice_id (first token on each line)
            voices = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # The voice ID is the first word before any whitespace or parenthesis
                voice_id = line.split()[0] if line.split() else line
                voices.append(voice_id)
            return sorted(voices)
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to list available voices: exit code %d, stderr: %s",
                e.returncode,
                e.stderr,
            )
            raise RuntimeError(f"Failed to fetch available voices: {e.stderr}") from e
        except subprocess.TimeoutExpired as e:
            logger.error("Timeout while fetching available voices")
            raise RuntimeError(
                "Timeout while fetching available voices from Piper"
            ) from e
        except Exception as e:
            logger.error("Failed to list available voices: %s", e)
            raise RuntimeError(f"Failed to fetch available voices: {e}") from e

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
            # Invalidate cached voice list so newly downloaded voice is recognized
            self._cached_voice_list = None
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to download voice '%s': exit code %d, stderr: %s",
                voice,
                e.returncode,
                e.stderr,
            )
            # Provide more helpful error messages for common failures
            error_msg = e.stderr.strip() if e.stderr else str(e)
            if "HTTP Error 404" in error_msg or "Not Found" in error_msg:
                raise RuntimeError(
                    f"Voice '{voice}' not found. The voice name may be incorrect or not available.\n"
                    f"Check the Piper TTS documentation for available voice models."
                ) from e
            raise RuntimeError(f"Voice download failed: {error_msg}") from e
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

    def download_voices_bulk(
        self,
        voices: list[str],
        max_workers: int = 3,
        progress_callback: Callable[[int, int], None] | None = None,
        stop_on_error: bool = False,
    ) -> tuple[int, int]:
        """Download multiple voice models in parallel.

        Args:
            voices: List of voice identifiers to download.
            max_workers: Maximum number of concurrent downloads (default: 3).
            progress_callback: Optional callback(completed, total) invoked after each
                             voice download completes (success or failure). The
                             completed count includes both successful and failed downloads.
            stop_on_error: If True, stop all downloads on the first error and raise.
                          If False (default), continue downloading remaining voices.

        Returns:
            A tuple (success_count, failure_count).

        Raises:
            RuntimeError: If stop_on_error=True and any download fails, or if
                         Piper TTS is not installed.
            ValueError: If the voices list is empty (returns (0, 0) instead).
        """
        if not voices:
            return (0, 0)

        total = len(voices)
        completed = 0
        failed = 0
        first_error: Exception | None = None

        # Use ThreadPoolExecutor for parallel downloads
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all download tasks
            future_to_voice = {
                executor.submit(self.download_voice, voice): voice for voice in voices
            }

            # Process results as they complete
            for future in as_completed(future_to_voice):
                voice = future_to_voice[future]
                try:
                    future.result()  # Will raise if download failed
                    completed += 1
                    logger.info("Successfully downloaded voice '%s'", voice)
                except Exception as e:
                    failed += 1
                    logger.error("Failed to download voice '%s': %s", voice, e)
                    if stop_on_error and first_error is None:
                        first_error = e
                        # Cancel all pending futures
                        for f in future_to_voice:
                            f.cancel()
                        # Break out of the loop; remaining futures may still run but we won't wait for them
                        break

                # Invoke progress callback if provided
                if progress_callback:
                    try:
                        progress_callback(completed + failed, total)
                    except Exception as e:
                        logger.warning("Progress callback raised exception: %s", e)

        # Clear voice cache to force refresh after bulk operation
        self._voice_cache.clear()
        # Invalidate cached voice list so newly downloaded voices are recognized
        self._cached_voice_list = None

        # If stop_on_error and an error occurred, raise now
        if stop_on_error and first_error is not None:
            raise RuntimeError(
                f"Bulk download stopped due to error: {first_error}"
            ) from first_error

        logger.info(
            "Bulk download completed: %d successful, %d failed",
            completed,
            failed,
        )
        return (completed, failed)

    def download_voices_by_language(
        self,
        language: str,
        quality: str | None = None,
        max_workers: int = 3,
        progress_callback: Callable[[int, int], None] | None = None,
        stop_on_error: bool = False,
    ) -> tuple[int, int]:
        """Download all voices for a given language (and optional quality) in bulk.

        This convenience method queries Piper's voice catalog, filters voices by
        language and quality, then downloads them using parallel execution.

        Args:
            language: Language code (e.g., "en_US", "fr_FR"). Voices whose ID
                     starts with this string will be selected.
            quality: Optional quality level (e.g., "medium", "high"). If provided,
                    only voices ending with "-{quality}" will be selected.
            max_workers: Maximum number of concurrent downloads (default: 3).
            progress_callback: Optional callback(completed, total) for progress updates.
            stop_on_error: If True, stop all downloads on first error. If False
                          (default), continue and return counts of successes/failures.

        Returns:
            Tuple (success_count, failure_count) from the bulk download operation.

        Raises:
            RuntimeError: If the voice catalog cannot be fetched or if stop_on_error=True
                         and any download fails.
        """
        # Get all available voices from Piper
        all_voices = self.list_available_voices()

        # Filter by language prefix and optional quality suffix
        if quality:
            quality_suffix = f"-{quality}"
            filtered_voices = [
                v
                for v in all_voices
                if v.startswith(language) and v.endswith(quality_suffix)
            ]
        else:
            filtered_voices = [v for v in all_voices if v.startswith(language)]

        if not filtered_voices:
            logger.warning(
                "No voices found for language '%s'%s. Nothing to download.",
                language,
                f" with quality '{quality}'" if quality else "",
            )
            return (0, 0)

        # Perform bulk download
        return self.download_voices_bulk(
            filtered_voices,
            max_workers=max_workers,
            progress_callback=progress_callback,
            stop_on_error=stop_on_error,
        )
