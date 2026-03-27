"""Configuration management for drinkingfountain.

This module provides dataclasses and a Config class for managing
application settings loaded from YAML configuration files.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
        backend: TTS backend to use ("piper", "coqui", or "transformers")
        audio: Audio configuration settings
        timing: Timing and pause settings
        voices: Mapping of character names to voice IDs
        prosody: Mapping of parenthetical cues to prosody parameters
    """

    backend: str = "piper"
    audio: AudioConfig = field(default_factory=AudioConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    voices: dict[str, str] = field(default_factory=dict)
    prosody: dict[str, ProsodyConfig] = field(default_factory=dict)

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

        # Build config objects
        audio_config = AudioConfig(**audio_data) if audio_data else AudioConfig()
        timing_config = TimingConfig(**timing_data) if timing_data else TimingConfig()

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

        # Validate backend
        valid_backends = ("piper", "coqui", "transformers")
        if self.backend not in valid_backends:
            errors.append(
                f"Invalid backend: {self.backend}. Must be one of {valid_backends}."
            )

        return errors
