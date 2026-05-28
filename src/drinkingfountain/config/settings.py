"""Configuration management for drinkingfountain.

This module provides dataclasses and a Config class for managing
application settings loaded from YAML configuration files.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from drinkingfountain.tts.factory import KNOWN_BACKENDS


@dataclass
class ProsodyConfig:
    """Prosody adjustment parameters for TTS synthesis.

    Attributes:
        speed: Speed multiplier (1.0 = normal, <1.0 slower, >1.0 faster)
        pitch: Pitch multiplier (1.0 = normal, <1.0 lower, >1.0 higher)
        volume: Volume multiplier (1.0 = normal, <1.0 quieter, >1.0 louder)
    """

    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0


@dataclass
class NarratorConfig:
    """Configuration for the narrator feature.

    Attributes:
        enabled: Whether the narrator is enabled (default: True)
        voice: Optional specific voice ID to use for narration. If None, uses default narrator voice.
        expand_int_ext: Whether to expand INT/EXT to Interior/Exterior (default: True)
        pause_before_narrative: Pause before narrative segments in seconds (default: 0.5)
        pause_after_narrative: Pause after narrative segments in seconds (default: 0.3)
        pause_after_heading: Pause after scene headings when narrator is speaking them.
            If None, uses timing.pause_after_scene_heading (default: None)
    """

    enabled: bool = True
    voice: str | None = None
    expand_int_ext: bool = True
    pause_before_narrative: float = 0.5
    pause_after_narrative: float = 0.3
    pause_after_heading: float | None = None

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.pause_before_narrative < 0:
            raise ValueError(
                f"Pause before narrative must be non-negative, got {self.pause_before_narrative}"
            )
        if self.pause_after_narrative < 0:
            raise ValueError(
                f"Pause after narrative must be non-negative, got {self.pause_after_narrative}"
            )
        if self.pause_after_heading is not None and self.pause_after_heading < 0:
            raise ValueError(
                f"Pause after heading must be non-negative, got {self.pause_after_heading}"
            )


@dataclass
class VoiceManagementConfig:
    """Configuration for voice management and bulk download operations.

    Attributes:
        bulk_download_language: Default language code for bulk voice downloads
            (e.g., "en_US", "es_ES"). If None, uses system default.
        bulk_download_quality: Default quality preset for bulk voice downloads.
            Supported values: "x-low", "low", "medium", "high", "x-high". If None, uses system default.
        max_concurrent_downloads: Maximum number of parallel download workers.
            Higher values increase parallelism but may strain network/resources.
    """

    bulk_download_language: str | None = None
    bulk_download_quality: str | None = None
    max_concurrent_downloads: int = 3

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.bulk_download_quality is not None:
            allowed_qualities = {"x-low", "low", "medium", "high", "x-high"}
            if self.bulk_download_quality not in allowed_qualities:
                raise ValueError(
                    f"Invalid bulk_download_quality: {self.bulk_download_quality}. "
                    f"Must be one of {sorted(allowed_qualities)} or None."
                )


@dataclass
class AudioConfig:
    """Audio output configuration.

    Attributes:
        sample_rate: Sample rate in Hz (must be 22050 or 44100)
        channels: Audio channel configuration ("mono" or "stereo")
        normalize: Whether to normalize audio to target level
        target_level: Target normalization level in dBFS (typically -3.0)
    """

    sample_rate: int = 22050
    channels: str = "mono"
    normalize: bool = True
    target_level: float = -3.0


@dataclass
class TimingConfig:
    """Timing and pause configuration for script rendering.

    Attributes:
        pause_between_lines: Pause between dialogue lines in seconds
        pause_after_scene_heading: Pause after scene headings in seconds
        pause_between_scenes: Pause between scenes in seconds
    """

    pause_between_lines: float = 0.3
    pause_after_scene_heading: float = 1.0
    pause_between_scenes: float = 2.0


@dataclass
class Config:
    """Main configuration container.

    Loads configuration from YAML files with fallback to defaults.

    Configuration is searched in the following order:
    1. Path provided to load()
    2. ./drinkingfountain.yaml (current directory)
    3. ~/.config/drinkingfountain/config.yaml (user config)

    Attributes:
        backend: TTS backend to use. "piper" is currently implemented;
            "kokoro-onnx" is reserved for the next local backend.
        audio: Audio configuration settings
        timing: Timing and pause settings
        voices: Mapping of character names to voice IDs
        prosody: Mapping of parenthetical cues to prosody parameters
        narrator: Narrator configuration for reading stage directions and scene headings
        voice_management: Voice management configuration for bulk downloads and
            parallel operations
    """

    backend: str = "piper"
    audio: AudioConfig = field(default_factory=AudioConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    voices: dict[str, str] = field(default_factory=dict)
    prosody: dict[str, ProsodyConfig] = field(default_factory=dict)
    narrator: NarratorConfig = field(default_factory=NarratorConfig)
    voice_management: VoiceManagementConfig = field(
        default_factory=VoiceManagementConfig
    )

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load configuration from a YAML file.

        If no path is provided, searches in standard locations.
        Returns a Config with defaults if no file is found.

        Args:
            path: Optional explicit path to configuration file

        Returns:
            Config object with loaded or default values

        Raises:
            yaml.YAMLError: If the configuration file contains invalid YAML
        """
        config_path = path or cls._find_config()

        if config_path is None or not config_path.exists():
            # No config file found, return defaults
            return cls()

        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Failed to parse YAML configuration: {e}") from e

        if data is None:
            # Empty config file
            return cls()

        return cls._from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from a dictionary (e.g., from web form data).

        Args:
            data: Dictionary containing configuration values

        Returns:
            Config object with values from dictionary
        """
        return cls._from_dict(data)

    @classmethod
    def _find_config(cls) -> Path | None:
        """Search for configuration file in standard locations.

        Returns:
            Path to config file if found, None otherwise
        """
        candidates = [
            Path.cwd() / "drinkingfountain.yaml",
            Path.home() / ".config" / "drinkingfountain" / "config.yaml",
        ]

        for path in candidates:
            if path.exists() and path.is_file():
                return path

        return None

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Construct Config from a dictionary (parsed YAML).

        Args:
            data: Dictionary containing configuration values

        Returns:
            Config object with values from dictionary
        """
        # Extract nested configurations
        audio_data = data.get("audio", {})
        timing_data = data.get("timing", {})
        voices_data = data.get("voices", {})
        prosody_data = data.get("prosody", {})
        narrator_data = data.get("narrator", {})
        voice_management_data = data.get("voice_management", {})

        # Build config objects
        audio_config = AudioConfig(**audio_data) if audio_data else AudioConfig()
        timing_config = TimingConfig(**timing_data) if timing_data else TimingConfig()
        narrator_config = (
            NarratorConfig(**narrator_data) if narrator_data else NarratorConfig()
        )
        voice_management_config = (
            VoiceManagementConfig(**voice_management_data)
            if voice_management_data
            else VoiceManagementConfig()
        )

        # Build prosody dict
        prosody_configs = {}
        for key, value in prosody_data.items():
            if isinstance(value, dict):
                prosody_configs[key] = ProsodyConfig(**value)
            else:
                # If it's just a number or something, treat as speed only
                prosody_configs[key] = ProsodyConfig(speed=float(value))

        return cls(
            backend=data.get("backend", "piper"),
            audio=audio_config,
            timing=timing_config,
            voices=voices_data,
            prosody=prosody_configs,
            narrator=narrator_config,
            voice_management=voice_management_config,
        )

    def validate(self) -> list[str]:
        """Validate configuration values.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Validate audio settings
        if self.audio.sample_rate not in (22050, 44100):
            errors.append(
                f"Invalid sample_rate: {self.audio.sample_rate}. "
                "Must be 22050 or 44100."
            )

        if self.audio.channels not in ("mono", "stereo"):
            errors.append(
                f"Invalid channels: {self.audio.channels}. Must be 'mono' or 'stereo'."
            )

        if self.audio.target_level > 0:
            errors.append(
                f"Invalid target_level: {self.audio.target_level}. "
                "Must be negative (dBFS)."
            )

        # Validate timing settings (all must be non-negative)
        if self.timing.pause_between_lines < 0:
            errors.append(
                f"Invalid pause_between_lines: {self.timing.pause_between_lines}. "
                "Must be non-negative."
            )

        if self.timing.pause_after_scene_heading < 0:
            errors.append(
                f"Invalid pause_after_scene_heading: {self.timing.pause_after_scene_heading}. "
                "Must be non-negative."
            )

        if self.timing.pause_between_scenes < 0:
            errors.append(
                f"Invalid pause_between_scenes: {self.timing.pause_between_scenes}. "
                "Must be non-negative."
            )

        # Validate prosody settings
        for key, prosody in self.prosody.items():
            if prosody.speed <= 0:
                errors.append(
                    f"Invalid prosody speed for '{key}': {prosody.speed}. "
                    "Must be positive."
                )
            if prosody.pitch <= 0:
                errors.append(
                    f"Invalid prosody pitch for '{key}': {prosody.pitch}. "
                    "Must be positive."
                )
            if prosody.volume <= 0:
                errors.append(
                    f"Invalid prosody volume for '{key}': {prosody.volume}. "
                    "Must be positive."
                )

        # Validate narrator settings
        # Note: NarratorConfig.__post_init__ already validates pause values,
        # but we need to catch any errors if the config was created with invalid values
        try:
            self.narrator.__post_init__()
        except ValueError as e:
            errors.append(f"Narrator configuration error: {e}")

        # Validate voice management settings
        if self.voice_management.max_concurrent_downloads < 1:
            errors.append(
                f"Invalid max_concurrent_downloads: {self.voice_management.max_concurrent_downloads}. "
                "Must be at least 1."
            )

        # Validate backend
        valid_backends = KNOWN_BACKENDS
        if self.backend not in valid_backends:
            errors.append(
                f"Invalid backend: {self.backend}. Must be one of {valid_backends}."
            )

        return errors
