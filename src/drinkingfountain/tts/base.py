"""Abstract base class for TTS backends."""

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydub import AudioSegment


@runtime_checkable
class TTSBackend(Protocol):
    """Protocol for a text-to-speech backend.

    A backend converts text to audio using a specific voice model.
    Implementations should be stateless or manage their own caching/state.
    """

    def generate_audio(self, text: str, voice: str) -> "AudioSegment":
        """Generate audio for the given text using the specified voice.

        Args:
            text: The text to synthesize (should be clean, without notes).
            voice: Identifier for the voice model to use.

        Returns:
            An AudioSegment containing the synthesized speech.

        Raises:
            FileNotFoundError: If the requested voice model is not found.
            RuntimeError: If synthesis fails for any reason.
        """
        ...

    def list_voices(self) -> list[str]:
        """Return a list of available voice identifiers.

        Returns:
            A list of voice IDs that can be used with generate_audio.
        """
        ...

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        """Download a voice model if not already available.

        Args:
            voice: The voice identifier to download.
            target_dir: Optional directory to download to. If None, uses
                       the backend's default voice directory.

        Raises:
            ValueError: If the voice identifier is invalid.
            RuntimeError: If download fails.
        """
        ...

    def is_available(self) -> bool:
        """Check if the backend is properly configured and ready.

        Returns:
            True if the backend can generate audio, False otherwise.
        """
        ...
