"""Voice assignment and management."""

import logging
import random
from collections.abc import MutableMapping

from ..tts.base import TTSBackend

logger = logging.getLogger(__name__)


class VoiceManager:
    """Manages voice assignment for characters and voice model downloads.

    The VoiceManager sits between the script and the TTS backend. It:
    - Tracks which voice to use for each character
    - Allows manual overrides (character -> voice)
    - Provides a default voice for unspecified characters
    - Auto-assigns voices from the available pool if no default set
    - Delegates voice listing and downloading to the backend
    """

    def __init__(self, backend: TTSBackend) -> None:
        """Initialize with a TTS backend.

        Args:
            backend: The TTS backend to use for synthesis and voice queries.
        """
        self.backend = backend
        self._overrides: MutableMapping[str, str] = {}
        self._default_voice: str | None = None
        self._auto_pool: list[str] = []
        self._char_voice_cache: dict[str, str] = {}  # per-character cache
        self._narrator_voice: str | None = None  # narrator voice to exclude

    def start_render(self) -> None:
        """Reset character voice cache at the start of a new render.

        This ensures consistent voice assignment throughout a single render
        while allowing different renders to use different assignments.
        """
        self._char_voice_cache.clear()
        # Also clear auto pool to refresh if voices changed
        self._auto_pool = []

    def set_narrator_voice(self, voice: str | None) -> None:
        """Set the narrator voice to exclude from auto-assignment pool.

        This should be called before rendering if narrator is enabled.
        Pass None to clear.

        Args:
            voice: Voice identifier, or None to clear.
        """
        self._narrator_voice = voice
        # Clear auto pool cache so exclusion takes effect
        self._auto_pool = []

    def set_character_voice(self, character: str, voice: str) -> None:
        """Assign a specific voice to a character.

        This override takes precedence over default and auto-assignment.

        Args:
            character: Character name (case-sensitive as in script).
            voice: Voice identifier from the backend.
        """
        self._overrides[character] = voice

    def set_default_voice(self, voice: str) -> None:
        """Set the default voice for characters without an explicit override.

        If no default is set, auto-assignment from the available pool is used.

        Args:
            voice: Voice identifier from the backend.
        """
        self._default_voice = voice

    def get_voice_for_character(self, character: str) -> str:
        """Get the voice ID to use for a given character.

        Resolution order:
        1. Explicit override for the character.
        2. Default voice if set.
        3. Random selection from available pool (excluding narrator).

        The result is cached for the duration of a render (until start_render()
        is called) to ensure consistency.

        Args:
            character: Character name.

        Returns:
            A voice identifier string.

        Raises:
            RuntimeError: If no voices are available from the backend.
            ValueError: If auto-assignment pool becomes empty after narrator exclusion.
        """
        # Check cache first (for consistency within a render)
        if character in self._char_voice_cache:
            return self._char_voice_cache[character]

        # Determine voice (same logic as before, but with narrator exclusion)
        if character in self._overrides:
            voice = self._overrides[character]
        elif self._default_voice:
            voice = self._default_voice
        else:
            # Auto-assign: build pool excluding narrator
            if not self._auto_pool:
                voices = self.backend.list_voices()
                if not voices:
                    raise RuntimeError(
                        "No voices available. Please download at least one voice model."
                    )
                # Exclude narrator voice from auto-assignment pool
                if self._narrator_voice:
                    original_count = len(voices)
                    voices = [v for v in voices if v != self._narrator_voice]
                    if original_count > 0 and len(voices) < original_count:
                        logger.debug(
                            "Excluded narrator voice '%s' from auto-assignment pool. "
                            "Pool size: %d -> %d",
                            self._narrator_voice,
                            original_count,
                            len(voices),
                        )
                    # Edge case: pool becomes empty after exclusion
                    if not voices:
                        raise ValueError(
                            "No voices available for character assignment. "
                            f"The narrator voice '{self._narrator_voice}' has been excluded, "
                            "leaving no voices for characters. Either add more voices or "
                            "assign specific voices to characters via configuration."
                        )
                self._auto_pool = voices.copy()
            voice = random.choice(self._auto_pool)

        # Cache for future calls in the same render
        self._char_voice_cache[character] = voice
        return voice

    def list_available_voices(self) -> list[str]:
        """Return the list of voices available from the backend."""
        return self.backend.list_voices()

    def download_voice(self, voice: str) -> None:
        """Download a voice model via the backend.

        Args:
            voice: Voice identifier to download.

        Raises:
            ValueError: If the voice identifier is invalid.
            RuntimeError: If download fails.
        """
        self.backend.download_voice(voice)
        # Clear caches so new voice is included
        self._auto_pool = []
        self._char_voice_cache.clear()

    def clear_overrides(self) -> None:
        """Remove all character-specific voice overrides."""
        self._overrides.clear()

    def get_overrides(self) -> dict[str, str]:
        """Get a copy of the current character voice overrides.

        The returned dictionary is a mutable copy; modifications do not affect
        the manager's internal state.
        """
        return dict(self._overrides)
