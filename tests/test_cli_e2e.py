"""End-to-end CLI tests using Click's CliRunner.

These tests invoke the actual `drinkingfountain render` command without mocking
the internal components (parser, mixer, config, voice manager). Only the TTS
backend is mocked to avoid requiring real Piper voice models.

This validates that the CLI properly wires all components together and the
user-facing command works correctly.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydub import AudioSegment

from drinkingfountain.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def simple_script_content() -> str:
    """Return a simple Fountain script content."""
    return """INT. ROOM - DAY

JOHN
Hello, world.

MARY
Hi there.
"""


@pytest.fixture
def temp_script_file(simple_script_content: str) -> Path:
    """Create a temporary Fountain script file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".fountain", delete=False) as f:
        f.write(simple_script_content)
        return Path(f.name)


@pytest.fixture
def mock_tts_instance():
    """Create a MagicMock for the TTS backend instance.

    This mock provides:
    - is_available() -> True by default (configurable)
    - list_voices() -> list of mock voices
    - generate_audio(text, voice) -> silent AudioSegment with realistic duration
    - download_voice(voice) -> does nothing
    - calls: list of (text, voice) tuples tracking generate_audio calls
    """
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.list_voices.return_value = ["voice1", "voice2", "voice3"]
    mock.calls = []  # Track calls for verification

    def generate_audio(text: str, voice: str):
        """Generate silent audio with duration based on text length."""
        mock.calls.append((text, voice))
        # Duration: 100ms base + 10ms per character
        duration_ms = 100 + int(len(text) * 10)
        return AudioSegment.silent(duration=duration_ms, frame_rate=22050)

    mock.generate_audio.side_effect = generate_audio
    mock.download_voice.return_value = None
    return mock


@pytest.fixture
def patched_piper(mock_tts_instance):
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


class TestRenderCommandE2E:
    """End-to-end tests for the render command."""

    def test_render_success_basic(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test basic successful render with mocked TTS (auto-assigned voices)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"

            result = runner.invoke(
                cli, ["render", str(temp_script_file), "-o", str(output_path)]
            )

            # Verify exit code 0
            assert result.exit_code == 0, (
                f"Command failed with output: {result.output}\n"
                f"Exception: {result.exception}"
            )

            # Verify output file was created
            assert output_path.exists()
            assert output_path.stat().st_size > 0

            # Verify CLI output contains success message
            assert "Render complete!" in result.output
            assert "Output:" in result.output
            assert "Duration:" in result.output
            assert "Time taken:" in result.output
            assert "TTS:" in result.output and "calls" in result.output

            # Verify TTS was called with expected texts
            # With narrator enabled by default, scene heading is also narrated
            assert len(mock_tts_instance.calls) == 3
            # First call should be the transformed scene heading
            assert mock_tts_instance.calls[0][0] == "Interior ROOM - DAY"
            # Next two are dialogue lines
            assert mock_tts_instance.calls[1][0] == "Hello, world."
            assert mock_tts_instance.calls[2][0] == "Hi there."
            # Voices should be from the available pool
            available_voices = {"voice1", "voice2", "voice3"}
            assert mock_tts_instance.calls[0][1] in available_voices
            assert mock_tts_instance.calls[1][1] in available_voices
            assert mock_tts_instance.calls[2][1] in available_voices

            # Verify the output audio is valid
            audio = AudioSegment.from_wav(output_path)
            assert audio.duration_seconds > 0
            # Expected: 1.0s heading pause + durations based on actual voice audio lengths
            # Since voice assignments are random, we can't predict exact duration, but it should be > 1.0
            assert audio.duration_seconds > 1.0

    def test_render_with_verbose(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with --verbose flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"

            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--verbose",
                ],
            )

            assert result.exit_code == 0
            assert output_path.exists()
            # Verbose should include debug logging
            assert "DEBUG" in result.output or "Generating audio" in result.output

    def test_render_with_custom_config(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with custom configuration file (explicit voice overrides)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"

            # Create a custom config with explicit voice assignments
            config_content = """audio:
  sample_rate: 44100
  channels: stereo
  normalize: false
timing:
  pause_between_lines: 0.5
  pause_after_scene_heading: 2.0
  pause_between_scenes: 3.0
voices:
  JOHN: voice1
  MARY: voice2
"""
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(config_content)

            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--config",
                    str(config_path),
                ],
            )

            assert result.exit_code == 0
            assert output_path.exists()

            # Verify TTS calls used the configured voices (including narrator for scene heading)
            assert len(mock_tts_instance.calls) == 3
            # Scene heading narrated with first available voice (voice1)
            assert mock_tts_instance.calls[0] == ("Interior ROOM - DAY", "voice1")
            # Dialogues use configured voices
            assert mock_tts_instance.calls[1] == ("Hello, world.", "voice1")
            assert mock_tts_instance.calls[2] == ("Hi there.", "voice2")

    def test_render_with_title_page_and_emphasized_character(
        self,
        runner: CliRunner,
        patched_piper,
        mock_tts_instance,
    ):
        """Test CLI render accepts title-page metadata and Markdown character cues."""
        script_content = """Title: FISSION EPISODE 101
Credit: written by
Author: Jonathan Golob
Notes:
The world's most dangerous technology. A disaster.
About the Author:
Jonathan Golob lives in Seattle.
Revision: 2026-03-24

# ACT I

.INT. FUKUSHIMA DAIICHI - CENTRAL CONTROL ROOM - DAY

CLAIRE
Welcome to the central control room.

**AUTOMATED VOICE**
(OVER SPEAKERS)
_Tri-tone alert._
This is an Earthquake Early Warning.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fission.fountain"
            output_path = Path(tmpdir) / "output.wav"
            script_path.write_text(script_content)

            result = runner.invoke(
                cli, ["render", str(script_path), "-o", str(output_path)]
            )

            assert result.exit_code == 0, (
                f"Command failed with output: {result.output}\n"
                f"Exception: {result.exception}"
            )
            assert output_path.exists()
            assert "Render complete!" in result.output

            spoken_text = [text for text, _voice in mock_tts_instance.calls]
            assert "Welcome to the central control room." in spoken_text
            assert (
                "_Tri-tone alert._\nThis is an Earthquake Early Warning." in spoken_text
            )
            assert all("FISSION EPISODE 101" not in text for text in spoken_text)

    def test_render_with_voices_dir(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with custom --voices-dir option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"
            voices_dir = Path(tmpdir) / "voices"
            voices_dir.mkdir()

            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--voices-dir",
                    str(voices_dir),
                ],
            )

            assert result.exit_code == 0
            assert output_path.exists()

            # Verify PiperTTSBackend was initialized with the custom voices_dir
            patched_piper.assert_called_once()
            call_kwargs = patched_piper.call_args[1]
            assert "voices_dir" in call_kwargs
            assert call_kwargs["voices_dir"] == voices_dir

    def test_render_with_cache_dir(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with custom --cache-dir option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"
            cache_dir = Path(tmpdir) / "cache"

            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

            assert result.exit_code == 0
            assert output_path.exists()

            # Since we patched CachedTTSBackend to bypass cache, the cache_dir
            # argument is ignored but the command should still succeed.

    def test_render_missing_script(
        self, runner: CliRunner, patched_piper, mock_tts_instance
    ):
        """Test render with non-existent script file."""
        result = runner.invoke(
            cli, ["render", "/nonexistent/script.fountain", "-o", "output.wav"]
        )

        # Click should exit with code 2 for missing file
        assert result.exit_code == 2
        assert "does not exist" in result.output or "Invalid value" in result.output

    @patch("drinkingfountain.services.StreamingAudioPlayer")
    def test_render_missing_output_option(
        self,
        mock_player_class: MagicMock,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render without --output option (should stream audio for playback)."""
        # Mock StreamingAudioPlayer to avoid real playback
        mock_player = MagicMock()
        mock_player_class.return_value = mock_player

        result = runner.invoke(cli, ["render", str(temp_script_file)])

        # Should succeed and stream audio
        assert result.exit_code == 0, (
            f"Command failed with output: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should show playback complete message
        assert "Playback complete!" in result.output
        # Verify StreamingAudioPlayer was created and finalized
        mock_player_class.assert_called_once()
        mock_player.finalize.assert_called_once()

    def test_render_tts_not_available(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render when TTS backend reports not available."""
        # Override is_available to return False
        mock_tts_instance.is_available.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"
            result = runner.invoke(
                cli, ["render", str(temp_script_file), "-o", str(output_path)]
            )

            assert result.exit_code == 1
            assert "Piper TTS is not available" in result.output

    def test_render_voice_model_not_found(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render when a voice model is not found."""

        # Make generate_audio raise FileNotFoundError for a specific voice
        def generate_audio_side_effect(text: str, voice: str):
            if voice == "voice2":
                raise FileNotFoundError(f"Voice model not found: {voice}")
            # Return silent audio for other voices
            duration_ms = 100 + int(len(text) * 10)
            return AudioSegment.silent(duration=duration_ms, frame_rate=22050)

        mock_tts_instance.generate_audio.side_effect = generate_audio_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.wav"

            # Create config that assigns MARY to voice2 (which will fail)
            config_content = """voices:
  JOHN: voice1
  MARY: voice2
"""
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(config_content)

            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--config",
                    str(config_path),
                ],
            )

            assert result.exit_code == 1
            assert "Voice model not found" in result.output

    def test_render_with_mp3_output(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with MP3 output format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"

            result = runner.invoke(
                cli, ["render", str(temp_script_file), "-o", str(output_path)]
            )

            assert result.exit_code == 0
            assert output_path.exists()
            assert output_path.suffix == ".mp3"

    def test_render_empty_script(
        self,
        runner: CliRunner,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with a script that has no dialogue."""
        # Create script with only scene heading
        script_content = "INT. ROOM - DAY"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".fountain", delete=False
        ) as f:
            f.write(script_content)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path)]
                )

                # The CLI should warn about no dialogue and exit with error
                assert result.exit_code == 1
                assert "No dialogue found" in result.output
        finally:
            script_path.unlink(missing_ok=True)

    def test_render_invalid_config_file(
        self,
        runner: CliRunner,
        temp_script_file: Path,
        patched_piper,
    ):
        """Test render with invalid YAML config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "bad_config.yaml"
            # Write invalid YAML
            config_path.write_text("audio:\n  sample_rate: [invalid\n")

            output_path = Path(tmpdir) / "output.wav"
            result = runner.invoke(
                cli,
                [
                    "render",
                    str(temp_script_file),
                    "-o",
                    str(output_path),
                    "--config",
                    str(config_path),
                ],
            )

            assert result.exit_code == 1
            assert "Configuration file is invalid YAML" in result.output

    def test_render_with_multiple_scenes(
        self,
        runner: CliRunner,
        patched_piper,
        mock_tts_instance,
    ):
        """Test render with a script containing multiple scenes."""
        script_content = """INT. HOUSE - DAY

JOHN
Hello.

EXT. PARK - NIGHT

MARY
Hi there.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".fountain", delete=False
        ) as f:
            f.write(script_content)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"
                result = runner.invoke(
                    cli, ["render", str(script_path), "-o", str(output_path)]
                )

                assert result.exit_code == 0
                assert output_path.exists()

                # Should have 4 TTS calls: 2 scene headings + 2 dialogues
                assert len(mock_tts_instance.calls) == 4
                # Check texts: first scene heading, then dialogue, then second heading, then dialogue
                assert mock_tts_instance.calls[0][0] == "Interior HOUSE - DAY"
                assert mock_tts_instance.calls[1][0] == "Hello."
                assert mock_tts_instance.calls[2][0] == "Exterior PARK - NIGHT"
                assert mock_tts_instance.calls[3][0] == "Hi there."
                available_voices = {"voice1", "voice2", "voice3"}
                for call in mock_tts_instance.calls:
                    assert call[1] in available_voices
        finally:
            script_path.unlink(missing_ok=True)

    def test_render_character_voice_auto_assignment(
        self,
        runner: CliRunner,
        patched_piper,
        mock_tts_instance,
    ):
        """Test that characters without explicit voice config get auto-assigned."""
        script_content = """INT. ROOM - DAY

JOHN
Hello.

MARY
Hi.
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".fountain", delete=False
        ) as f:
            f.write(script_content)
            script_path = Path(f.name)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "output.wav"

                # Only configure voice for JOHN, leave MARY to auto-assign
                config_content = """voices:
  JOHN: voice1
"""
                config_path = Path(tmpdir) / "config.yaml"
                config_path.write_text(config_content)

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
                assert output_path.exists()

                # Verify TTS calls (including scene heading)
                assert len(mock_tts_instance.calls) == 3
                # Scene heading narrated with first available voice (voice1)
                assert mock_tts_instance.calls[0] == ("Interior ROOM - DAY", "voice1")
                # JOHN should use voice1 explicitly (override)
                assert mock_tts_instance.calls[1] == ("Hello.", "voice1")
                # MARY should auto-assign to some voice from the pool
                assert mock_tts_instance.calls[2][0] == "Hi."
                available_voices = {"voice1", "voice2", "voice3"}
                assert mock_tts_instance.calls[2][1] in available_voices
        finally:
            script_path.unlink(missing_ok=True)
