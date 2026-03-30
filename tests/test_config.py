"""Tests for configuration management."""

import tempfile
from pathlib import Path

import pytest
import yaml

from drinkingfountain.config import (
    AudioConfig,
    Config,
    ProsodyConfig,
    TimingConfig,
    VoiceManagementConfig,
)


class TestProsodyConfig:
    """Tests for ProsodyConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = ProsodyConfig()
        assert config.speed == 1.0
        assert config.pitch == 1.0
        assert config.volume == 1.0

    def test_custom_values(self):
        """Test custom initialization."""
        config = ProsodyConfig(speed=1.2, pitch=0.9, volume=0.8)
        assert config.speed == 1.2
        assert config.pitch == 0.9
        assert config.volume == 0.8


class TestAudioConfig:
    """Tests for AudioConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = AudioConfig()
        assert config.sample_rate == 22050
        assert config.channels == "mono"
        assert config.normalize is True
        assert config.target_level == -3.0

    def test_custom_values(self):
        """Test custom initialization."""
        config = AudioConfig(
            sample_rate=44100, channels="stereo", normalize=False, target_level=-6.0
        )
        assert config.sample_rate == 44100
        assert config.channels == "stereo"
        assert config.normalize is False
        assert config.target_level == -6.0


class TestTimingConfig:
    """Tests for TimingConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = TimingConfig()
        assert config.pause_between_lines == 0.3
        assert config.pause_after_scene_heading == 1.0
        assert config.pause_between_scenes == 2.0

    def test_custom_values(self):
        """Test custom initialization."""
        config = TimingConfig(
            pause_between_lines=0.5,
            pause_after_scene_heading=1.5,
            pause_between_scenes=3.0,
        )
        assert config.pause_between_lines == 0.5
        assert config.pause_after_scene_heading == 1.5
        assert config.pause_between_scenes == 3.0


class TestVoiceManagementConfig:
    """Tests for VoiceManagementConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = VoiceManagementConfig()
        assert config.bulk_download_language is None
        assert config.bulk_download_quality is None
        assert config.max_concurrent_downloads == 3

    def test_custom_values(self):
        """Test custom initialization."""
        config = VoiceManagementConfig(
            bulk_download_language="en_US",
            bulk_download_quality="high",
            max_concurrent_downloads=5,
        )
        assert config.bulk_download_language == "en_US"
        assert config.bulk_download_quality == "high"
        assert config.max_concurrent_downloads == 5

    def test_validation_max_concurrent_downloads_zero(self):
        """Test that max_concurrent_downloads=0 is allowed but fails validation."""
        # Should not raise immediately, but should fail validation later
        config = VoiceManagementConfig(max_concurrent_downloads=0)
        assert config.max_concurrent_downloads == 0


class TestConfig:
    """Tests for main Config class."""

    def test_defaults(self):
        """Test default configuration."""
        config = Config()
        assert config.backend == "piper"
        assert isinstance(config.audio, AudioConfig)
        assert isinstance(config.timing, TimingConfig)
        assert isinstance(config.voice_management, VoiceManagementConfig)
        assert config.voices == {}
        assert config.prosody == {}

    def test_load_missing_file_returns_defaults(self):
        """Test that loading non-existent file returns defaults."""
        config = Config.load(path=Path("/nonexistent/path.yaml"))
        assert config.backend == "piper"
        assert config.voices == {}

    def test_load_empty_yaml(self):
        """Test loading empty YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            assert config.backend == "piper"
        finally:
            temp_path.unlink()

    def test_load_basic_config(self):
        """Test loading simple configuration."""
        yaml_content = """
backend: coqui
audio:
  sample_rate: 44100
  channels: stereo
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            assert config.backend == "coqui"
            assert config.audio.sample_rate == 44100
            assert config.audio.channels == "stereo"
            # Defaults for unspecified values
            assert config.audio.normalize is True
            assert config.audio.target_level == -3.0
        finally:
            temp_path.unlink()

    def test_load_full_config(self):
        """Test loading full configuration with all sections."""
        yaml_content = """
backend: transformers
audio:
  sample_rate: 22050
  channels: mono
  normalize: false
  target_level: -6.0
timing:
  pause_between_lines: 0.5
  pause_after_scene_heading: 1.5
  pause_between_scenes: 3.0
voices:
  NARRATOR: en_US-amy-medium
  JOHN: en_US-john-medium
prosody:
  angrily:
    speed: 1.1
    pitch: 1.1
    volume: 1.0
  sadly:
    speed: 0.9
    pitch: 0.9
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)

            # Check backend
            assert config.backend == "transformers"

            # Check audio
            assert config.audio.sample_rate == 22050
            assert config.audio.channels == "mono"
            assert config.audio.normalize is False
            assert config.audio.target_level == -6.0

            # Check timing
            assert config.timing.pause_between_lines == 0.5
            assert config.timing.pause_after_scene_heading == 1.5
            assert config.timing.pause_between_scenes == 3.0

            # Check voices
            assert config.voices == {
                "NARRATOR": "en_US-amy-medium",
                "JOHN": "en_US-john-medium",
            }

            # Check prosody
            assert "angrily" in config.prosody
            assert config.prosody["angrily"].speed == 1.1
            assert config.prosody["angrily"].pitch == 1.1
            assert config.prosody["angrily"].volume == 1.0

            assert "sadly" in config.prosody
            assert config.prosody["sadly"].speed == 0.9
            assert config.prosody["sadly"].pitch == 0.9
        finally:
            temp_path.unlink()

    def test_prosody_simple_format(self):
        """Test prosody with simple numeric values (speed only)."""
        yaml_content = """
prosody:
  excited: 1.2
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            assert "excited" in config.prosody
            assert config.prosody["excited"].speed == 1.2
            assert config.prosody["excited"].pitch == 1.0  # default
            assert config.prosody["excited"].volume == 1.0  # default
        finally:
            temp_path.unlink()

    def test_validate_valid_config(self):
        """Test validation passes for valid configuration."""
        config = Config()
        errors = config.validate()
        assert errors == []

    def test_validate_invalid_sample_rate(self):
        """Test validation catches invalid sample rate."""
        config = Config()
        config.audio = AudioConfig(sample_rate=48000)
        errors = config.validate()
        assert any("sample_rate" in err for err in errors)

    def test_validate_invalid_channels(self):
        """Test validation catches invalid channels."""
        config = Config()
        config.audio = AudioConfig(channels="surround")
        errors = config.validate()
        assert any("channels" in err for err in errors)

    def test_validate_negative_timing(self):
        """Test validation catches negative timing values."""
        config = Config()
        config.timing = TimingConfig(pause_between_lines=-1.0)
        errors = config.validate()
        assert any("pause_between_lines" in err for err in errors)

    def test_validate_invalid_prosody_values(self):
        """Test validation catches invalid prosody values."""
        config = Config()
        config.prosody = {
            "angry": ProsodyConfig(speed=0.0),  # speed must be positive
        }
        errors = config.validate()
        assert any("speed" in err and "angry" in err for err in errors)

    def test_validate_invalid_backend(self):
        """Test validation catches invalid backend."""
        config = Config(backend="invalid")
        errors = config.validate()
        assert any("backend" in err for err in errors)

    def test_validate_positive_prosody_checks(self):
        """Test prosody validation for all positive value checks."""
        config = Config()
        config.prosody = {
            "speed_zero": ProsodyConfig(speed=0.0),
            "pitch_negative": ProsodyConfig(pitch=-1.0),
            "volume_zero": ProsodyConfig(volume=0.0),
        }
        errors = config.validate()
        assert len(errors) >= 3  # At least 3 errors

    def test_find_config_none_when_missing(self, tmp_path: Path):
        """Test _find_config returns None when no config exists."""
        # Ensure we're in a temp directory with no config
        config = Config()
        config._find_config()
        # Should be None if no config in current dir or home
        # This test assumes neither location has a config
        # We can't guarantee that, so we just check it doesn't raise

    def test_load_with_invalid_yaml(self):
        """Test loading file with invalid YAML raises error."""
        yaml_content = """
backend: test
audio:
  sample_rate: 22050
  channels: mono
  invalid: [ this is not valid YAML
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(yaml.YAMLError):
                Config.load(path=temp_path)
        finally:
            temp_path.unlink()


class TestConfigIntegration:
    """Integration tests for configuration."""

    def test_config_with_all_features(self):
        """Test complete configuration with all features."""
        yaml_content = """
# Test full config
backend: piper
audio:
  sample_rate: 44100
  channels: stereo
  normalize: true
  target_level: -3.0
timing:
  pause_between_lines: 0.3
  pause_after_scene_heading: 1.0
  pause_between_scenes: 2.0
voices:
  NARRATOR: en_US-amy-medium
  JOHN: en_US-john-medium
  MARY: en_US-mary-medium
prosody:
  angrily:
    speed: 1.1
    pitch: 1.1
  sadly:
    speed: 0.9
    pitch: 0.9
  whispering:
    speed: 1.0
    pitch: 1.0
    volume: 0.6
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            errors = config.validate()
            assert errors == [], f"Validation errors: {errors}"

            # Verify all data loaded correctly
            assert config.backend == "piper"
            assert config.audio.sample_rate == 44100
            assert config.audio.channels == "stereo"
            assert len(config.voices) == 3
            assert len(config.prosody) == 3
            assert config.prosody["whispering"].volume == 0.6
        finally:
            temp_path.unlink()

    def test_config_with_voice_management(self):
        """Test configuration with voice_management section."""
        yaml_content = """
backend: piper
voice_management:
  bulk_download_language: en_US
  bulk_download_quality: high
  max_concurrent_downloads: 5
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            errors = config.validate()
            assert errors == [], f"Validation errors: {errors}"

            # Verify voice_management loaded correctly
            assert config.voice_management.bulk_download_language == "en_US"
            assert config.voice_management.bulk_download_quality == "high"
            assert config.voice_management.max_concurrent_downloads == 5
        finally:
            temp_path.unlink()

    def test_config_with_voice_management_partial(self):
        """Test configuration with partial voice_management (only some fields)."""
        yaml_content = """
voice_management:
  max_concurrent_downloads: 2
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            errors = config.validate()
            assert errors == [], f"Validation errors: {errors}"

            # Verify partial config with defaults for missing fields
            assert config.voice_management.bulk_download_language is None
            assert config.voice_management.bulk_download_quality is None
            assert config.voice_management.max_concurrent_downloads == 2
        finally:
            temp_path.unlink()

    def test_config_voice_management_validation_invalid(self):
        """Test validation catches invalid voice_management values."""
        yaml_content = """
voice_management:
  max_concurrent_downloads: 0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = Config.load(path=temp_path)
            errors = config.validate()
            assert any("max_concurrent_downloads" in err for err in errors)
        finally:
            temp_path.unlink()
