"""Tests for the narrator feature."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydub import AudioSegment

from drinkingfountain.audio import AudioMixer, AudioConfig, TimingConfig
from drinkingfountain.config import Config, NarratorConfig
from drinkingfountain.utils.narrator import transform_scene_heading
from drinkingfountain.cli import cli


class TestTransformSceneHeading:
    """Tests for transform_scene_heading function."""

    def test_int_expanded(self):
        """INT should be expanded to Interior."""
        assert transform_scene_heading("INT. HOUSE - DAY") == "Interior HOUSE - DAY"

    def test_int_no_period(self):
        """INT without period should be expanded."""
        assert transform_scene_heading("INT HOUSE - DAY") == "Interior HOUSE - DAY"

    def test_int_lowercase(self):
        """Lowercase int should be expanded."""
        assert transform_scene_heading("int. house - day") == "Interior house - day"

    def test_ext_expanded(self):
        """EXT should be expanded to Exterior."""
        assert transform_scene_heading("EXT. PARK") == "Exterior PARK"

    def test_ext_no_period(self):
        """EXT without period should be expanded."""
        assert transform_scene_heading("EXT PARK") == "Exterior PARK"

    def test_no_change_when_disabled(self):
        """When expand_int_ext is False, text should be unchanged."""
        text = "INT. HOUSE - DAY"
        assert transform_scene_heading(text, expand_int_ext=False) == text

    def test_non_matching_text(self):
        """Text not starting with INT/EXT should be unchanged."""
        text = "FADE IN."
        assert transform_scene_heading(text) == text

    def test_whitespace_handling(self):
        """Should handle leading whitespace correctly."""
        assert transform_scene_heading("  INT. ROOM") == "  Interior ROOM"

    def test_mixed_case_with_period(self):
        """Mixed case with period should be handled."""
        assert transform_scene_heading("Int.Room") == "InteriorRoom"
        assert transform_scene_heading("Ext.Park") == "ExteriorPark"


class TestNarratorConfig:
    """Tests for NarratorConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = NarratorConfig()
        assert config.enabled is True
        assert config.voice is None
        assert config.expand_int_ext is True
        assert config.pause_before_narrative == 0.5
        assert config.pause_after_narrative == 0.3
        assert config.pause_after_heading is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = NarratorConfig(
            enabled=False,
            voice="custom_voice",
            expand_int_ext=False,
            pause_before_narrative=1.0,
            pause_after_narrative=0.5,
            pause_after_heading=2.0,
        )
        assert config.enabled is False
        assert config.voice == "custom_voice"
        assert config.expand_int_ext is False
        assert config.pause_before_narrative == 1.0
        assert config.pause_after_narrative == 0.5
        assert config.pause_after_heading == 2.0

    def test_negative_pause_before_raises(self):
        """Negative pause_before_narrative should raise ValueError."""
        with pytest.raises(ValueError, match="Pause before narrative must be non-negative"):
            NarratorConfig(pause_before_narrative=-0.5)

    def test_negative_pause_after_raises(self):
        """Negative pause_after_narrative should raise ValueError."""
        with pytest.raises(ValueError, match="Pause after narrative must be non-negative"):
            NarratorConfig(pause_after_narrative=-0.3)

    def test_negative_pause_after_heading_raises(self):
        """Negative pause_after_heading should raise ValueError."""
        with pytest.raises(ValueError, match="Pause after heading must be non-negative"):
            NarratorConfig(pause_after_heading=-1.0)

    def test_zero_pauses_allowed(self):
        """Zero pause values should be allowed."""
        config = NarratorConfig(pause_before_narrative=0.0, pause_after_narrative=0.0, pause_after_heading=0.0)
        assert config.pause_before_narrative == 0.0
        assert config.pause_after_narrative == 0.0
        assert config.pause_after_heading == 0.0


class TestNarratorInConfig:
    """Tests for NarratorConfig integration into Config."""

    def test_config_default_narrator(self):
        """Config should have default NarratorConfig."""
        config = Config()
        assert isinstance(config.narrator, NarratorConfig)
        assert config.narrator.enabled is True

    def test_config_load_narrator_from_yaml(self):
        """Config should load narrator settings from YAML."""
        yaml_content = """
narrator:
  enabled: false
  voice: custom_voice
  expand_int_ext: false
  pause_before_narrative: 1.0
  pause_after_narrative: 0.5
  pause_after_heading: 2.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            config = Config.load(config_path)
            assert config.narrator.enabled is False
            assert config.narrator.voice == "custom_voice"
            assert config.narrator.expand_int_ext is False
            assert config.narrator.pause_before_narrative == 1.0
            assert config.narrator.pause_after_narrative == 0.5
            assert config.narrator.pause_after_heading == 2.0
        finally:
            config_path.unlink(missing_ok=True)

    def test_config_validate_narrator_negative_pauses(self):
        """Config validation should catch invalid narrator pause values."""
        config = Config()
        config.narrator.pause_before_narrative = -1.0
        errors = config.validate()
        assert any("Narrator configuration error" in e for e in errors)

    def test_config_validate_narrator_valid(self):
        """Config validation should pass with valid narrator config."""
        config = Config()
        errors = config.validate()
        assert not errors or not any("narrator" in e.lower() for e in errors)


class TestAudioMixerAddNarrative:
    """Tests for AudioMixer.add_narrative method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.audio_config = AudioConfig()
        self.timing_config = TimingConfig()
        self.mixer = AudioMixer(self.audio_config, self.timing_config)
        self.action_block = MagicMock()
        self.action_block.content = "Test action"
        self.action_block.__class__.__name__ = "Action"

    def test_add_narrative_with_pauses(self):
        """Test adding narrative with custom pauses."""
        audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        self.mixer.add_narrative(
            self.action_block,
            audio,
            pause_before=0.5,
            pause_after=0.3,
        )
        # Should have: pause, audio, pause = 3 segments
        assert len(self.mixer.segments) == 3
        # Check state
        assert self.mixer.state.last_block_type.value == "action"
        assert self.mixer.state.in_scene is True
        # Check duration: 0.5s + 1.0s + 0.3s = 1.8s
        assert self.mixer.duration() == pytest.approx(1.8, rel=0.01)

    def test_add_narrative_no_pause_before(self):
        """Test adding narrative with no pause before."""
        audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        self.mixer.add_narrative(
            self.action_block,
            audio,
            pause_before=0.0,
            pause_after=0.3,
        )
        assert len(self.mixer.segments) == 2  # audio + pause
        assert self.mixer.duration() == pytest.approx(1.3, rel=0.01)

    def test_add_narrative_no_pause_after(self):
        """Test adding narrative with no pause after."""
        audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        self.mixer.add_narrative(
            self.action_block,
            audio,
            pause_before=0.5,
            pause_after=0.0,
        )
        assert len(self.mixer.segments) == 2  # pause + audio
        assert self.mixer.duration() == pytest.approx(1.5, rel=0.01)

    def test_add_narrative_invalid_audio_raises(self):
        """Test that non-AudioSegment raises ValueError."""
        with pytest.raises(ValueError, match="Expected AudioSegment"):
            self.mixer.add_narrative(self.action_block, "not audio")

    def test_add_narrative_state_updated(self):
        """Test that state is properly updated after adding narrative."""
        audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        # First add something else to set initial state
        dialogue_block = MagicMock()
        dialogue_block.character = "Test"
        dialogue_audio = AudioSegment.silent(duration=500, frame_rate=22050)
        self.mixer.add_dialogue(dialogue_block, dialogue_audio)

        # Now add narrative
        self.mixer.add_narrative(self.action_block, audio)
        assert self.mixer.state.last_block_type.value == "action"
        assert self.mixer.state.in_scene is True


class TestNarratorCLIIntegration:
    """Tests for narrator integration in CLI."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def simple_script(self) -> str:
        """Return a simple Fountain script."""
        return """INT. ROOM - DAY

JOHN
Hello.

Action line here.
"""

    @pytest.fixture
    def mock_tts_instance(self):
        """Create a MagicMock for the TTS backend instance."""
        mock = MagicMock()
        mock.is_available.return_value = True
        mock.list_voices.return_value = ["voice1", "voice2", "voice3"]
        mock.calls = []  # Track calls

        def generate_audio(text: str, voice: str):
            mock.calls.append((text, voice))
            duration_ms = 100 + int(len(text) * 10)
            return AudioSegment.silent(duration=duration_ms, frame_rate=22050)

        mock.generate_audio.side_effect = generate_audio
        mock.download_voice.return_value = None
        return mock

    @pytest.fixture
    def patched_piper(self, mock_tts_instance):
        """Patch PiperTTSBackend and CachedTTSBackend to use the mock without caching."""
        with (
            patch("drinkingfountain.cli.PiperTTSBackend") as mock_piper_class,
            patch("drinkingfountain.cli.CachedTTSBackend") as mock_cached_class,
        ):
            mock_piper_class.return_value = mock_tts_instance
            # Make CachedTTSBackend just return the backend directly (no caching)
            def passthrough(backend, cache_dir=None):
                return backend
            mock_cached_class.side_effect = passthrough
            yield mock_piper_class

    def test_render_with_narrator_enabled_by_default(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that narrator is enabled by default and scene headings are narrated."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path)]
                )

                assert result.exit_code == 0
                # Should have calls for: scene heading, dialogue, action = 3
                assert len(mock_tts_instance.calls) == 3
                # Check that scene heading was transformed
                assert any(call[0] == "Interior ROOM - DAY" for call in mock_tts_instance.calls)
                # Check that action was narrated
                assert any(call[0] == "Action line here." for call in mock_tts_instance.calls)
        finally:
            script_path.unlink(missing_ok=True)

    def test_render_with_no_narrator_flag(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that --no-narrator disables narration."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path), "--no-narrator"]
                )

                assert result.exit_code == 0
                # Should have calls only for dialogue = 1 (no scene heading, no action)
                assert len(mock_tts_instance.calls) == 1
                assert mock_tts_instance.calls[0][0] == "Hello."
        finally:
            script_path.unlink(missing_ok=True)

    def test_narrator_graceful_degradation_on_tts_error(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that narrator disables gracefully on TTS error and continues with dialogue."""
        # Make TTS fail on first call (scene heading) but succeed on dialogue
        call_count = [0]

        def generate_audio_side_effect(text: str, voice: str):
            call_count[0] += 1
            if call_count[0] == 1:  # First call (scene heading)
                raise RuntimeError("TTS synthesis failed: channels not specified")
            mock_tts_instance.calls.append((text, voice))
            duration_ms = 100 + int(len(text) * 10)
            return AudioSegment.silent(duration=duration_ms, frame_rate=22050)

        mock_tts_instance.generate_audio.side_effect = generate_audio_side_effect

        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path)]
                )

                assert result.exit_code == 0
                # Should have warning about narrator error
                assert "Warning: Narrator TTS error" in result.output
                assert "Disabling narrator" in result.output
                # Dialogue should still be rendered (1 call for dialogue)
                # Action should be skipped because narrator disabled
                # Only successful calls are recorded: dialogue = 1
                assert len(mock_tts_instance.calls) == 1
                # The dialogue call should be present
                assert mock_tts_instance.calls[0][0] == "Hello."
        finally:
            script_path.unlink(missing_ok=True)

    def test_narrator_custom_voice(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that narrator uses specified voice from config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_content = """narrator:
  voice: voice2
"""
                config_path = Path(tmpdir) / "config.yaml"
                config_path.write_text(config_content)

                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli,
                    [
                        "render",
                        str(script_path),
                        "-o",
                        str(output_path),
                        "--config",
                        str(config_path),
                    ],
                )

                assert result.exit_code == 0
                # Check that narrator voice used is voice2 for scene heading
                heading_calls = [call for call in mock_tts_instance.calls if call[0] == "Interior ROOM - DAY"]
                assert len(heading_calls) == 1
                assert heading_calls[0][1] == "voice2"
        finally:
            script_path.unlink(missing_ok=True)

    def test_narrator_uses_default_voice_when_none_specified(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that narrator uses first available voice when none specified."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path)]
                )

                assert result.exit_code == 0
                # Check that narrator used voice1 (first available)
                heading_calls = [call for call in mock_tts_instance.calls if call[0] == "Interior ROOM - DAY"]
                assert len(heading_calls) == 1
                assert heading_calls[0][1] == "voice1"
        finally:
            script_path.unlink(missing_ok=True)

    def test_narrator_warns_if_specified_voice_not_found(
        self, runner, simple_script, patched_piper, mock_tts_instance
    ):
        """Test that warning is shown if configured narrator voice is not available."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
            f.write(simple_script)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_content = """narrator:
  voice: nonexistent_voice
"""
                config_path = Path(tmpdir) / "config.yaml"
                config_path.write_text(config_content)

                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli,
                    [
                        "render",
                        str(script_path),
                        "-o",
                        str(output_path),
                        "--config",
                        str(config_path),
                    ],
                )

                assert result.exit_code == 0
                assert "Specified narrator voice 'nonexistent_voice' not found" in result.output
                # Should still render using first available voice
                assert len(mock_tts_instance.calls) >= 1
        finally:
            script_path.unlink(missing_ok=True)
