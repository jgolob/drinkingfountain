"""Tests for the drinkingfountain CLI."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from drinkingfountain.cli import cli
from drinkingfountain.parser.script import Dialogue


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_script() -> Path:
    """Create a temporary Fountain script."""
    content = """INT. HOUSE - DAY

JOHN
Hello, world!

MARY
How are you today?

JOHN
I'm fine, thank you.
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
        f.write(content)
        return Path(f.name)


class TestCLIBasic:
    """Test basic CLI functionality."""

    def test_cli_help(self, runner: CliRunner) -> None:
        """Test that --help works."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "DrinkingFountain" in result.output
        assert "render" in result.output
        assert "voices" in result.output

    def test_render_help(self, runner: CliRunner) -> None:
        """Test render command help."""
        result = runner.invoke(cli, ["render", "--help"])
        assert result.exit_code == 0
        assert "Render a Fountain script to audio" in result.output
        assert "--output" in result.output

    def test_voices_help(self, runner: CliRunner) -> None:
        """Test voices command help."""
        result = runner.invoke(cli, ["voices", "--help"])
        assert result.exit_code == 0
        assert "Manage voice models" in result.output

    def test_voices_list_help(self, runner: CliRunner) -> None:
        """Test voices list help."""
        result = runner.invoke(cli, ["voices", "list", "--help"])
        assert result.exit_code == 0
        assert "List available voice models" in result.output


class TestRenderCommand:
    """Test the render command."""

    @patch("drinkingfountain.cli.PiperTTSBackend")
    @patch("drinkingfountain.cli.FountainParser")
    def test_render_missing_script(
        self, mock_parser: MagicMock, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test render with non-existent script."""
        result = runner.invoke(
            cli, ["render", "nonexistent.fountain", "-o", "output.wav"]
        )
        assert result.exit_code == 2  # Click exits with 2 for missing argument/file
        assert "does not exist" in result.output

    @patch("drinkingfountain.cli._play_mix")
    @patch("drinkingfountain.cli.PiperTTSBackend")
    @patch("drinkingfountain.cli.FountainParser")
    def test_render_no_output(
        self,
        mock_parser: MagicMock,
        mock_piper: MagicMock,
        mock_play_mix: MagicMock,
        runner: CliRunner,
        temp_script: Path,
    ) -> None:
        """Test render without --output option (should stream audio for playback)."""
        # Setup mocks
        mock_piper.return_value.is_available.return_value = True
        mock_piper.return_value.list_voices.return_value = ["voice1"]

        mock_script = MagicMock()
        mock_script.title = "Test Script"

        # Create a scene with dialogue blocks
        scene1 = MagicMock()
        scene1.heading = MagicMock(content="Scene 1")
        dialogue1 = MagicMock(spec=Dialogue)
        dialogue1.character = "JOHN"
        dialogue1.content = "Hello, world!"
        scene1.blocks = [dialogue1]

        mock_script.scenes = [scene1]
        mock_script.characters = {"JOHN"}
        mock_parser.return_value.parse.return_value = mock_script

        # Mock voice manager
        with patch("drinkingfountain.cli.VoiceManager") as mock_voice_mgr_class:
            mock_voice_mgr = MagicMock()
            mock_voice_mgr.get_voice_for_character.return_value = "voice1"
            mock_voice_mgr_class.return_value = mock_voice_mgr

            # Mock TTS audio generation
            from pydub import AudioSegment

            mock_audio = AudioSegment.silent(duration=1000)
            mock_piper.return_value.generate_audio.return_value = mock_audio

            # Use real AudioMixer (not mocked) with real silent audio
            # The mixer will be constructed normally and use the mock audio

            result = runner.invoke(cli, ["render", str(temp_script)])

            # Should succeed
            assert result.exit_code == 0, (
                f"Output: {result.output}\nError: {result.exception}"
            )
            assert "Playback complete!" in result.output
            # _play_mix should be called
            mock_play_mix.assert_called_once()

    @patch("drinkingfountain.cli.PiperTTSBackend")
    @patch("drinkingfountain.cli.FountainParser")
    def test_render_tts_not_available(
        self,
        mock_parser: MagicMock,
        mock_piper: MagicMock,
        runner: CliRunner,
        temp_script: Path,
    ) -> None:
        """Test render when TTS is not available."""
        mock_piper.return_value.is_available.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "output.wav"
            result = runner.invoke(cli, ["render", str(temp_script), "-o", str(output)])

            assert result.exit_code == 1
            assert "Piper TTS is not available" in result.output

    @patch("drinkingfountain.cli.VoiceManager")
    @patch("drinkingfountain.cli.PiperTTSBackend")
    @patch("drinkingfountain.cli.FountainParser")
    def test_render_success(
        self,
        mock_parser: MagicMock,
        mock_piper: MagicMock,
        mock_voice_mgr_class: MagicMock,
        runner: CliRunner,
        temp_script: Path,
    ) -> None:
        """Test successful render (mocked)."""
        # Setup mocks
        mock_piper.return_value.is_available.return_value = True
        mock_piper.return_value.list_voices.return_value = ["voice1"]

        mock_script = MagicMock()
        mock_script.title = "Test Script"

        # Create a scene with dialogue blocks
        scene1 = MagicMock()
        scene1.heading = MagicMock(content="Scene 1")
        dialogue1 = MagicMock(spec=Dialogue)
        dialogue1.character = "JOHN"
        dialogue1.content = "Hello, world!"
        dialogue2 = MagicMock(spec=Dialogue)
        dialogue2.character = "MARY"
        dialogue2.content = "How are you today?"
        dialogue3 = MagicMock(spec=Dialogue)
        dialogue3.character = "JOHN"
        dialogue3.content = "I'm fine, thank you."
        scene1.blocks = [dialogue1, dialogue2, dialogue3]

        mock_script.scenes = [scene1]
        mock_script.characters = {"JOHN", "MARY"}
        mock_parser.return_value.parse.return_value = mock_script

        # Mock voice manager instance
        mock_voice_mgr = MagicMock()
        mock_voice_mgr.get_voice_for_character.return_value = "voice1"
        mock_voice_mgr_class.return_value = mock_voice_mgr

        # Mock TTS audio generation
        from pydub import AudioSegment

        mock_audio = AudioSegment.silent(duration=1000)
        mock_piper.return_value.generate_audio.return_value = mock_audio

        # Mock mixer
        with patch("drinkingfountain.cli.AudioMixer") as mock_mixer_class:
            mock_mixer = MagicMock()
            mock_mixer.duration.return_value = 5.0
            mock_mixer_class.return_value = mock_mixer

            with tempfile.TemporaryDirectory() as tmpdir:
                output = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(temp_script), "-o", str(output)]
                )

                # Should succeed
                assert result.exit_code == 0, (
                    f"Output: {result.output}\nError: {result.exception}"
                )
                assert "Render complete" in result.output
                assert "Dialogue lines: 3" in result.output

    def test_render_invalid_config(self, runner: CliRunner, temp_script: Path) -> None:
        """Test render with invalid configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an invalid config file
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("audio:\n  sample_rate: 12345\n")

            output = Path(tmpdir) / "output.wav"
            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script),
                    "-o",
                    str(output),
                    "--config",
                    str(config_path),
                ],
            )

            assert result.exit_code == 1
            assert "Configuration errors" in result.output


class TestVoicesCommand:
    """Test the voices command group."""

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_list_empty(self, mock_piper: MagicMock, runner: CliRunner) -> None:
        """Test voices list when no voices are available."""
        mock_piper.return_value.list_voices.return_value = []

        result = runner.invoke(cli, ["voices", "list"])
        assert result.exit_code == 0
        assert "No voice models found" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_list_success(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices list with some voices."""
        mock_piper.return_value.list_voices.return_value = [
            "en_US-amy-medium",
            "en_US-john-medium",
        ]

        result = runner.invoke(cli, ["voices", "list"])
        assert result.exit_code == 0
        assert "Available voices (2):" in result.output
        assert "en_US-amy-medium" in result.output
        assert "en_US-john-medium" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_download(self, mock_piper: MagicMock, runner: CliRunner) -> None:
        """Test voices download."""
        mock_piper.return_value.voices_dir = Path("/tmp/voices")

        result = runner.invoke(cli, ["voices", "download", "test_voice"])
        assert result.exit_code == 0
        assert "Downloading voice 'test_voice'" in result.output
        assert "downloaded to" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_test_save(self, mock_piper: MagicMock, runner: CliRunner) -> None:
        """Test voices test with output file."""
        from pydub import AudioSegment

        mock_piper.return_value.list_voices.return_value = ["test_voice"]
        mock_piper.return_value.generate_audio.return_value = AudioSegment.silent(
            duration=500
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.wav"
            result = runner.invoke(
                cli,
                [
                    "voices",
                    "test",
                    "test_voice",
                    "Hello world",
                    "--output",
                    str(output),
                ],
            )

            assert result.exit_code == 0
            assert "Generating audio" in result.output
            assert "Audio saved to" in result.output
            assert output.exists()

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_test_voice_not_found(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices test with non-existent voice."""
        mock_piper.return_value.list_voices.return_value = ["other_voice"]

        result = runner.invoke(cli, ["voices", "test", "test_voice", "Hello"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_available_list(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices available command with list format."""
        mock_piper.return_value.list_available_voices.return_value = [
            "en_US-amy-medium",
            "en_US-john-medium",
            "fr_FR-henri-medium",
        ]

        result = runner.invoke(cli, ["voices", "available"])
        assert result.exit_code == 0, (
            f"Output: {result.output}\nError: {result.exception}"
        )
        assert "Available voices for download (3):" in result.output
        assert "en_US-amy-medium" in result.output
        assert "en_US-john-medium" in result.output
        assert "fr_FR-henri-medium" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_available_json(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices available command with JSON format."""
        mock_piper.return_value.list_available_voices.return_value = [
            "en_US-amy-medium",
            "en_US-john-medium",
        ]

        result = runner.invoke(cli, ["voices", "available", "--format", "json"])
        assert result.exit_code == 0, (
            f"Output: {result.output}\nError: {result.exception}"
        )
        # Should be valid JSON array of strings
        import json

        data = json.loads(result.output)
        assert data == ["en_US-amy-medium", "en_US-john-medium"]

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_available_filter_by_language(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices available command with language filter."""
        mock_piper.return_value.list_available_voices.return_value = [
            "en_US-amy-medium",
            "en_US-john-medium",
            "fr_FR-henri-medium",
        ]

        result = runner.invoke(cli, ["voices", "available", "--language", "en_US"])
        assert result.exit_code == 0
        assert "Available voices for download (2):" in result.output
        assert "en_US-amy-medium" in result.output
        assert "en_US-john-medium" in result.output
        assert "fr_FR-henri-medium" not in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_available_empty(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices available when no voices are available."""
        mock_piper.return_value.list_available_voices.return_value = []

        result = runner.invoke(cli, ["voices", "available"])
        assert result.exit_code == 0
        assert "No voices match the criteria" in result.output

    @patch("drinkingfountain.cli.PiperTTSBackend")
    def test_voices_available_piper_not_installed(
        self, mock_piper: MagicMock, runner: CliRunner
    ) -> None:
        """Test voices available when Piper is not installed."""
        mock_piper.return_value.list_available_voices.side_effect = RuntimeError(
            "Piper TTS is not installed"
        )

        result = runner.invoke(cli, ["voices", "available"])
        assert result.exit_code == 1
        assert "Error: Piper TTS is not installed" in result.output


class TestPlayMixFunction:
    """Tests for the _play_mix helper function."""

    def test_play_mix_success(self, runner: CliRunner) -> None:
        """Test _play_mix with successful playback."""
        from pydub import AudioSegment

        from drinkingfountain.cli import _play_mix

        # Create a mock simpleaudio module
        mock_sa = MagicMock()
        mock_play_obj = MagicMock()
        mock_sa.play_buffer.return_value = mock_play_obj

        with patch.dict("sys.modules", {"simpleaudio": mock_sa}):
            mock_audio = AudioSegment.silent(duration=1000, frame_rate=22050)
            _play_mix(mock_audio)
            mock_sa.play_buffer.assert_called_once()
            mock_play_obj.wait_done.assert_called_once()

    def test_play_mix_missing_simpleaudio(self, runner: CliRunner) -> None:
        """Test _play_mix when simpleaudio is not installed."""
        from pydub import AudioSegment

        from drinkingfountain.cli import _play_mix

        # Ensure simpleaudio is not available
        with patch.dict("sys.modules", {"simpleaudio": None}):
            mock_audio = AudioSegment.silent(duration=1000)
            with pytest.raises(SystemExit) as exc_info:
                _play_mix(mock_audio)
            assert exc_info.value.code == 1

    def test_play_mix_keyboard_interrupt(self, runner: CliRunner) -> None:
        """Test _play_mix when user presses Ctrl+C."""
        from pydub import AudioSegment

        from drinkingfountain.cli import _play_mix

        mock_sa = MagicMock()
        mock_play_obj = MagicMock()
        mock_sa.play_buffer.return_value = mock_play_obj
        mock_play_obj.wait_done.side_effect = KeyboardInterrupt

        with patch.dict("sys.modules", {"simpleaudio": mock_sa}):
            mock_audio = AudioSegment.silent(duration=1000)
            with pytest.raises(SystemExit) as exc_info:
                _play_mix(mock_audio)
            assert exc_info.value.code == 0

    def test_play_mix_playback_error(self, runner: CliRunner) -> None:
        """Test _play_mix when playback fails."""
        from pydub import AudioSegment

        from drinkingfountain.cli import _play_mix

        mock_sa = MagicMock()
        mock_sa.play_buffer.side_effect = RuntimeError("Playback failed")

        with patch.dict("sys.modules", {"simpleaudio": mock_sa}):
            mock_audio = AudioSegment.silent(duration=1000)
            with pytest.raises(SystemExit) as exc_info:
                _play_mix(mock_audio)
            assert exc_info.value.code == 1
