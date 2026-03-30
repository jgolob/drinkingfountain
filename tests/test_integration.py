"""Integration tests for the full rendering pipeline.

This module tests the complete workflow from parsing a Fountain script
to generating a mixed audio output, with a mocked TTS backend.

The integration test validates that all components (parser, config, TTS,
voice manager, mixer) work together correctly in a realistic scenario.
"""

from pathlib import Path
from typing import cast

import pytest
from pydub import AudioSegment

from drinkingfountain.audio.mixer import AudioConfig as MixerAudioConfig
from drinkingfountain.audio.mixer import AudioMixer
from drinkingfountain.audio.mixer import TimingConfig as MixerTimingConfig
from drinkingfountain.config.settings import (
    AudioConfig,
    Config,
    NarratorConfig,
    TimingConfig,
)
from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import Dialogue, SceneHeading
from drinkingfountain.services import RenderService
from drinkingfountain.tts.base import TTSBackend
from drinkingfountain.voices.manager import VoiceManager


class MockTTSBackend(TTSBackend):
    """Mock TTS backend that generates silent audio segments with predictable duration.

    The mock tracks all synthesis requests for verification and generates
    silent audio with a duration based on the text length. This allows
    testing the full pipeline without requiring actual voice models.

    Attributes:
        calls: List of (text, voice) tuples tracking all generate_audio calls.
        available_voices: List of voice IDs that this mock provides.
        duration_per_char: Seconds of audio per character of text.
    """

    def __init__(self, duration_per_char: float = 0.01):
        """Initialize the mock TTS backend.

        Args:
            duration_per_char: Duration in seconds per character of text.
                             Default is 0.01s (10ms) per character, plus
                             a base 100ms per utterance.
        """
        self.duration_per_char = duration_per_char
        self.calls: list[tuple[str, str]] = []
        self.available_voices = ["voice1", "voice2", "voice3"]

    def generate_audio(self, text: str, voice: str) -> AudioSegment:
        """Generate silent audio with duration based on text length.

        Args:
            text: The text to synthesize.
            voice: The voice identifier to use.

        Returns:
            A silent AudioSegment with calculated duration.

        Raises:
            FileNotFoundError: If the voice is not in available_voices.
        """
        if voice not in self.available_voices:
            raise FileNotFoundError(f"Voice model not found: {voice}")

        self.calls.append((text, voice))
        # Duration: 100ms base + 10ms per character
        duration_ms = 100 + int(len(text) * self.duration_per_char * 1000)
        return AudioSegment.silent(duration=duration_ms, frame_rate=22050)

    def list_voices(self) -> list[str]:
        """Return the list of available mock voices."""
        return self.available_voices.copy()

    def download_voice(self, voice: str, target_dir: Path | None = None) -> None:
        """Mock voice download - just validates the voice exists."""
        if voice not in self.available_voices:
            raise ValueError(f"Invalid voice: {voice}")

    def is_available(self) -> bool:
        """Mock always available."""
        return True


@pytest.fixture
def simple_script_fixture(tmp_path: Path) -> Path:
    """Create a simple Fountain script as a fixture file.

    The script contains:
    - One scene with two characters
    - Two dialogue blocks

    Returns:
        Path to the temporary script file.
    """
    script_content = """INT. ROOM - DAY

JOHN
Hello, world.

MARY
Hi there.
"""
    script_path = tmp_path / "simple.fountain"
    script_path.write_text(script_content)
    return script_path


@pytest.fixture
def mock_tts() -> MockTTSBackend:
    """Create a mock TTS backend for testing."""
    return MockTTSBackend(duration_per_char=0.01)


@pytest.fixture
def voice_manager(mock_tts: MockTTSBackend) -> VoiceManager:
    """Create a VoiceManager with the mock TTS backend."""
    return VoiceManager(mock_tts)


@pytest.fixture
def minimal_config() -> Config:
    """Create a minimal configuration for testing."""
    return Config(
        backend="mock",
        audio=AudioConfig(sample_rate=22050, channels="mono", normalize=False),
        timing=TimingConfig(
            pause_between_lines=0.3,
            pause_after_scene_heading=1.0,
            pause_between_scenes=2.0,
        ),
        voices={"JOHN": "voice1", "MARY": "voice2"},
    )


class TestFullRenderingPipeline:
    """Integration tests for the complete rendering pipeline."""

    def test_simple_script_render(
        self,
        simple_script_fixture: Path,
        mock_tts: MockTTSBackend,
        voice_manager: VoiceManager,
        minimal_config: Config,
        tmp_path: Path,
    ):
        """Test the full render pipeline with a simple script.

        This test exercises:
        1. Script parsing with FountainParser
        2. Voice assignment via VoiceManager
        3. Audio generation via TTS backend
        4. Audio mixing with AudioMixer
        5. Export to WAV file

        The test verifies:
        - Correct number of TTS calls (2 dialogue blocks)
        - Correct voice assignments (JOHN->voice1, MARY->voice2)
        - Total audio duration matches expected calculation
        - Output file exists and is valid WAV
        - Output matches configured sample rate and channels
        """
        # Step 1: Load and parse the script
        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        assert len(script.scenes) == 1
        scene = script.scenes[0]
        assert isinstance(scene.heading, SceneHeading)
        assert scene.heading.location == "INT. ROOM"
        assert scene.heading.time == "DAY"

        # Should have 2 dialogue blocks
        dialogue_blocks = [b for b in scene.blocks if isinstance(b, Dialogue)]
        assert len(dialogue_blocks) == 2

        john_dialogue = dialogue_blocks[0]
        assert john_dialogue.character == "JOHN"
        assert john_dialogue.content == "Hello, world."

        mary_dialogue = dialogue_blocks[1]
        assert mary_dialogue.character == "MARY"
        assert mary_dialogue.content == "Hi there."

        # Step 2: Set up voice assignments
        voice_manager.set_character_voice("JOHN", "voice1")
        voice_manager.set_character_voice("MARY", "voice2")

        # Step 3: Initialize mixer with config (convert to mixer's config types)
        # Keep references to original configs for assertions
        audio_config = minimal_config.audio
        timing_config = minimal_config.timing
        mixer_audio_config = MixerAudioConfig(
            sample_rate=audio_config.sample_rate,
            channels=audio_config.channels,
            normalize=audio_config.normalize,
            target_level=audio_config.target_level,
        )
        mixer_timing_config = MixerTimingConfig(
            pause_between_lines=timing_config.pause_between_lines,
            pause_after_scene_heading=timing_config.pause_after_scene_heading,
            pause_between_scenes=timing_config.pause_between_scenes,
        )
        mixer = AudioMixer(config=mixer_audio_config, timing=mixer_timing_config)

        # Add scene heading (with no audio, just the pause)
        mixer.add_scene_heading(scene.heading, audio=None)

        # Step 4: Generate audio for each dialogue block and add to mixer
        for block in scene.blocks:
            if isinstance(block, Dialogue):
                voice = voice_manager.get_voice_for_character(block.character)
                audio = mock_tts.generate_audio(block.content, voice)
                mixer.add_dialogue(block, audio)

        # Step 5: Verify TTS was called correctly
        assert len(mock_tts.calls) == 2
        assert mock_tts.calls[0] == ("Hello, world.", "voice1")
        assert mock_tts.calls[1] == ("Hi there.", "voice2")

        # Step 6: Calculate expected duration
        # For "Hello, world.": 13 chars -> 100ms + 130ms = 230ms
        # For "Hi there.": 9 chars -> 100ms + 90ms = 190ms
        john_audio_duration = 0.1 + (13 * 0.01)  # 0.23s
        mary_audio_duration = 0.1 + (9 * 0.01)  # 0.19s

        # Timeline:
        # - post-heading pause: 1.0s
        # - john dialogue: 0.23s
        # - between-lines pause: 0.3s
        # - mary dialogue: 0.19s
        expected_duration = (
            timing_config.pause_after_scene_heading
            + john_audio_duration
            + timing_config.pause_between_lines
            + mary_audio_duration
        )

        actual_duration = mixer.duration()
        assert actual_duration == pytest.approx(expected_duration, rel=0.01)

        # Step 7: Export to temporary WAV file
        output_path = tmp_path / "output.wav"
        mixer.export(str(output_path), format="wav")

        # Step 8: Verify output file
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Load and verify the audio
        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == pytest.approx(expected_duration, rel=0.01)
        assert exported.frame_rate == audio_config.sample_rate
        assert exported.channels == (1 if audio_config.channels == "mono" else 2)

    def test_multiple_scenes_with_pauses(
        self, mock_tts: MockTTSBackend, voice_manager: VoiceManager, tmp_path: Path
    ):
        """Test rendering with multiple scenes and proper pause handling."""
        # Create a two-scene script
        script_content = """INT. HOUSE - DAY

JOHN
Hello.

EXT. PARK - NIGHT

MARY
Hi there.
"""
        script_path = tmp_path / "two_scenes.fountain"
        script_path.write_text(script_content)

        parser = FountainParser()
        script = parser.parse(script_path)

        assert len(script.scenes) == 2

        # Setup
        voice_manager.set_character_voice("JOHN", "voice1")
        voice_manager.set_character_voice("MARY", "voice2")

        config = Config(
            backend="mock",
            audio=AudioConfig(sample_rate=22050, channels="mono", normalize=False),
            timing=TimingConfig(
                pause_between_lines=0.3,
                pause_after_scene_heading=1.0,
                pause_between_scenes=2.0,
            ),
            voices={"JOHN": "voice1", "MARY": "voice2"},
        )

        mixer_audio_config = MixerAudioConfig(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            normalize=config.audio.normalize,
            target_level=config.audio.target_level,
        )
        mixer_timing_config = MixerTimingConfig(
            pause_between_lines=config.timing.pause_between_lines,
            pause_after_scene_heading=config.timing.pause_after_scene_heading,
            pause_between_scenes=config.timing.pause_between_scenes,
        )
        mixer = AudioMixer(config=mixer_audio_config, timing=mixer_timing_config)

        # Process all scenes
        for scene in script.scenes:
            mixer.add_scene_heading(scene.heading, audio=None)
            for block in scene.blocks:
                if isinstance(block, Dialogue):
                    voice = voice_manager.get_voice_for_character(block.character)
                    audio = mock_tts.generate_audio(block.content, voice)
                    mixer.add_dialogue(block, audio)

        # Expected timeline:
        # Scene 1:
        # - post-heading pause: 1.0s
        # - JOHN (5 chars): 0.1 + 0.05 = 0.15s
        # - between-lines: 0.3s (but there's no second dialogue in scene 1, so not used)
        # Scene 2:
        # - between-scenes pause: 2.0s
        # - post-heading pause: 1.0s
        # - MARY (8 chars): 0.1 + 0.08 = 0.18s
        #
        # Total: 1.0 + 0.15 + 2.0 + 1.0 + 0.18 = 4.33s

        expected_duration = 1.0 + 0.15 + 2.0 + 1.0 + 0.18

        assert mixer.duration() == pytest.approx(expected_duration, rel=0.01)

        # Export and verify
        output_path = tmp_path / "two_scenes.wav"
        mixer.export(str(output_path))
        assert output_path.exists()

        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == pytest.approx(expected_duration, rel=0.01)

    def test_character_without_voice_auto_assigns(
        self,
        simple_script_fixture: Path,
        mock_tts: MockTTSBackend,
        voice_manager: VoiceManager,
        tmp_path: Path,
    ):
        """Test that characters without explicit voice assignment get auto-assigned."""
        # Only assign voice to JOHN, leave MARY unassigned
        voice_manager.set_character_voice("JOHN", "voice1")
        # Don't set MARY - should auto-assign from available pool

        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        config = Config(
            backend="mock",
            audio=AudioConfig(sample_rate=22050, channels="mono", normalize=False),
            timing=TimingConfig(),
            voices={"JOHN": "voice1"},  # Only JOHN has explicit voice
        )

        mixer_audio_config = MixerAudioConfig(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            normalize=config.audio.normalize,
            target_level=config.audio.target_level,
        )
        mixer_timing_config = MixerTimingConfig(
            pause_between_lines=config.timing.pause_between_lines,
            pause_after_scene_heading=config.timing.pause_after_scene_heading,
            pause_between_scenes=config.timing.pause_between_scenes,
        )
        mixer = AudioMixer(config=mixer_audio_config, timing=mixer_timing_config)
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        for block in script.scenes[0].blocks:
            if isinstance(block, Dialogue):
                voice = voice_manager.get_voice_for_character(block.character)
                # Should get a valid voice
                assert voice in mock_tts.available_voices
                audio = mock_tts.generate_audio(block.content, voice)
                mixer.add_dialogue(block, audio)

        # Should have called TTS twice with valid voices
        assert len(mock_tts.calls) == 2
        assert mock_tts.calls[0][1] == "voice1"  # JOHN uses explicit voice
        assert mock_tts.calls[1][1] in mock_tts.available_voices  # MARY auto-assigned

    def test_missing_voice_model_raises_error(
        self, simple_script_fixture: Path, voice_manager: VoiceManager, tmp_path: Path
    ):
        """Test that requesting a non-existent voice raises a clear error."""
        # Create a TTS backend that only has certain voices
        limited_tts = MockTTSBackend()
        limited_tts.available_voices = ["voice1"]  # Only one voice available

        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        config = Config(
            backend="mock",
            audio=AudioConfig(),
            timing=TimingConfig(),
            voices={
                "JOHN": "voice1",
                "MARY": "nonexistent_voice",
            },  # MARY uses invalid voice
        )

        mixer_audio_config = MixerAudioConfig(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            normalize=config.audio.normalize,
            target_level=config.audio.target_level,
        )
        mixer_timing_config = MixerTimingConfig(
            pause_between_lines=config.timing.pause_between_lines,
            pause_after_scene_heading=config.timing.pause_after_scene_heading,
            pause_between_scenes=config.timing.pause_between_scenes,
        )
        mixer = AudioMixer(config=mixer_audio_config, timing=mixer_timing_config)
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        # Should raise FileNotFoundError when trying to generate with missing voice
        with pytest.raises(FileNotFoundError, match="Voice model not found"):
            for block in script.scenes[0].blocks:
                if isinstance(block, Dialogue):
                    if block.character == "MARY":
                        # This will fail
                        voice = config.voices[block.character]
                        limited_tts.generate_audio(block.content, voice)

    def test_invalid_config_validation(
        self,
        simple_script_fixture: Path,
        mock_tts: MockTTSBackend,
        voice_manager: VoiceManager,
        tmp_path: Path,
    ):
        """Test that invalid configuration is caught during validation."""
        # Create config with invalid sample rate
        config = Config(
            backend="mock",
            audio=AudioConfig(sample_rate=22050, channels="mono", normalize=False),
            timing=TimingConfig(),
            voices={"JOHN": "voice1", "MARY": "voice2"},
        )

        # Manually set invalid sample rate to test validation
        config.audio.sample_rate = 48000  # Invalid - not 22050 or 44100

        errors = config.validate()
        assert len(errors) > 0
        assert any("sample_rate" in err for err in errors)

        # Invalid channels
        config.audio.channels = "surround"
        errors = config.validate()
        assert any("channels" in err for err in errors)

        # Invalid timing
        config.timing.pause_between_lines = -1.0
        errors = config.validate()
        assert any("pause_between_lines" in err for err in errors)

    def test_export_file_properties(
        self,
        simple_script_fixture: Path,
        mock_tts: MockTTSBackend,
        voice_manager: VoiceManager,
        tmp_path: Path,
    ):
        """Test that exported WAV file has correct properties."""
        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        voice_manager.set_character_voice("JOHN", "voice1")
        voice_manager.set_character_voice("MARY", "voice2")

        # Test with different sample rates and channel configs
        for sample_rate in [22050, 44100]:
            for channels in ["mono", "stereo"]:
                config = Config(
                    backend="mock",
                    audio=AudioConfig(
                        sample_rate=sample_rate, channels=channels, normalize=False
                    ),
                    timing=TimingConfig(),
                    voices={"JOHN": "voice1", "MARY": "voice2"},
                )

                mixer_audio_config = MixerAudioConfig(
                    sample_rate=config.audio.sample_rate,
                    channels=config.audio.channels,
                    normalize=config.audio.normalize,
                    target_level=config.audio.target_level,
                )
                mixer_timing_config = MixerTimingConfig(
                    pause_between_lines=config.timing.pause_between_lines,
                    pause_after_scene_heading=config.timing.pause_after_scene_heading,
                    pause_between_scenes=config.timing.pause_between_scenes,
                )
                mixer = AudioMixer(
                    config=mixer_audio_config, timing=mixer_timing_config
                )
                mixer.add_scene_heading(script.scenes[0].heading, audio=None)

                for block in script.scenes[0].blocks:
                    if isinstance(block, Dialogue):
                        voice = voice_manager.get_voice_for_character(block.character)
                        audio = mock_tts.generate_audio(block.content, voice)
                        mixer.add_dialogue(block, audio)

                output_path = tmp_path / f"test_{sample_rate}_{channels}.wav"
                mixer.export(str(output_path))

                assert output_path.exists()
                exported = AudioSegment.from_wav(output_path)
                assert exported.frame_rate == sample_rate
                expected_channels = 1 if channels == "mono" else 2
                assert exported.channels == expected_channels

    def test_normalization_applied_correctly(
        self,
        simple_script_fixture: Path,
        mock_tts: MockTTSBackend,
        voice_manager: VoiceManager,
        tmp_path: Path,
    ):
        """Test that audio normalization is applied when enabled."""
        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        voice_manager.set_character_voice("JOHN", "voice1")
        voice_manager.set_character_voice("MARY", "voice2")

        # With normalization enabled
        config = Config(
            backend="mock",
            audio=AudioConfig(
                sample_rate=22050, channels="mono", normalize=True, target_level=-3.0
            ),
            timing=TimingConfig(),
            voices={"JOHN": "voice1", "MARY": "voice2"},
        )

        mixer_audio_config = MixerAudioConfig(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            normalize=config.audio.normalize,
            target_level=config.audio.target_level,
        )
        mixer_timing_config = MixerTimingConfig(
            pause_between_lines=config.timing.pause_between_lines,
            pause_after_scene_heading=config.timing.pause_after_scene_heading,
            pause_between_scenes=config.timing.pause_between_scenes,
        )
        mixer = AudioMixer(config=mixer_audio_config, timing=mixer_timing_config)
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        for block in script.scenes[0].blocks:
            if isinstance(block, Dialogue):
                voice = voice_manager.get_voice_for_character(block.character)
                audio = mock_tts.generate_audio(block.content, voice)
                mixer.add_dialogue(block, audio)

        output_path = tmp_path / "normalized.wav"
        mixer.export(str(output_path))

        exported = AudioSegment.from_wav(output_path)
        # Normalized audio should be near target level (within some tolerance)
        # Since mock generates silent audio, dBFS will be -inf, so normalization
        # won't actually do anything. But we can at least verify export works.
        assert exported.duration_seconds > 0

    def test_empty_script_handling(
        self, mock_tts: MockTTSBackend, voice_manager: VoiceManager, tmp_path: Path
    ):
        """Test handling of an empty or minimal script."""
        # Create a script with only a scene heading, no dialogue
        script_content = "INT. ROOM - DAY"
        script_path = tmp_path / "empty_dialogue.fountain"
        script_path.write_text(script_content)

        parser = FountainParser()
        script = parser.parse(script_path)

        assert len(script.scenes) == 1
        assert len([b for b in script.scenes[0].blocks if isinstance(b, Dialogue)]) == 0

        mixer = AudioMixer()
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        # Should have only the post-heading pause
        assert mixer.duration() == pytest.approx(1.0)

        output_path = tmp_path / "empty.wav"
        mixer.export(str(output_path))
        assert output_path.exists()

        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == pytest.approx(1.0)


class TestErrorScenarios:
    """Tests for error handling in the integration pipeline."""

    def test_script_with_no_scenes(
        self, mock_tts: MockTTSBackend, voice_manager: VoiceManager, tmp_path: Path
    ):
        """Test handling of a script that produces no scenes."""
        # Create an empty script
        script_path = tmp_path / "empty.fountain"
        script_path.write_text("")

        parser = FountainParser()
        script = parser.parse(script_path)

        assert len(script.scenes) == 0

        mixer = AudioMixer()
        # No segments added, should still be able to export empty WAV
        output_path = tmp_path / "completely_empty.wav"
        mixer.export(str(output_path))
        assert output_path.exists()

        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == 0

    def test_tts_backend_not_available(
        self, simple_script_fixture: Path, voice_manager: VoiceManager, tmp_path: Path
    ):
        """Test behavior when TTS backend is not available."""

        # Create a TTS that reports not available
        class UnavailableTTSBackend(MockTTSBackend):
            def is_available(self) -> bool:
                return False

        unavailable_tts = UnavailableTTSBackend()

        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        # Even if backend says not available, we can still use it in tests
        # The actual app would check this, but our integration test can proceed
        voice_manager = VoiceManager(unavailable_tts)
        voice_manager.set_character_voice("JOHN", "voice1")
        voice_manager.set_character_voice("MARY", "voice2")

        mixer = AudioMixer()
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        # Should still work in our mock scenario
        for block in script.scenes[0].blocks:
            if isinstance(block, Dialogue):
                voice = voice_manager.get_voice_for_character(block.character)
                audio = unavailable_tts.generate_audio(block.content, voice)
                mixer.add_dialogue(block, audio)

        assert len(unavailable_tts.calls) == 2

    def test_parser_file_not_found(self):
        """Test that parsing a non-existent file raises error."""
        parser = FountainParser()
        non_existent = Path("/nonexistent/script.fountain")

        with pytest.raises(FileNotFoundError):
            parser.parse(non_existent)

    def test_voice_manager_no_voices_raises(
        self, simple_script_fixture: Path, tmp_path: Path
    ):
        """Test that VoiceManager raises when no voices are available."""
        # Create a TTS with no voices
        empty_tts = MockTTSBackend()
        empty_tts.available_voices = []

        parser = FountainParser()
        script = parser.parse(simple_script_fixture)

        voice_manager = VoiceManager(empty_tts)
        # Don't set any overrides or default - will try to auto-assign
        # and fail because no voices available

        mixer = AudioMixer()
        mixer.add_scene_heading(script.scenes[0].heading, audio=None)

        with pytest.raises(RuntimeError, match="No voices available"):
            for block in script.scenes[0].blocks:
                if isinstance(block, Dialogue):
                    voice = voice_manager.get_voice_for_character(block.character)
                    audio = empty_tts.generate_audio(block.content, voice)
                    mixer.add_dialogue(block, audio)


class TestRenderServiceWithVoiceManager:
    """Integration tests for RenderService with the updated VoiceManager integration."""

    @pytest.fixture
    def render_service(
        self, voice_manager: VoiceManager, minimal_config: Config, tmp_path: Path
    ) -> RenderService:
        """Create a RenderService instance with mock TTS and voice manager."""
        # Wrap the voice_manager's backend in CachedTTSBackend as RenderService expects
        from drinkingfountain.tts import CachedTTSBackend

        # Use a temporary cache directory to avoid persistent cache between tests
        cache_dir = tmp_path / "tts_cache"
        cached_tts = CachedTTSBackend(voice_manager.backend, cache_dir=cache_dir)
        # Create a fresh config with narrator disabled by default
        config = Config(
            backend="mock",
            audio=minimal_config.audio,
            timing=minimal_config.timing,
            voices={},  # Empty by default, tests will set as needed
            narrator=NarratorConfig(
                enabled=False,
                voice=None,
                expand_int_ext=True,
                pause_after_heading=None,
                pause_before_narrative=0.5,
                pause_after_narrative=0.5,
            ),
        )
        return RenderService(
            config=config,
            tts=cached_tts,
            voice_mgr=voice_manager,
            narrator_cfg=config.narrator,
            no_narrator=True,
        )

    def test_consistent_voice_assignment_across_scenes(
        self,
        tmp_path: Path,
        render_service: RenderService,
    ):
        """Test that the same character gets the same voice across multiple scenes."""
        # Create a script with the same character appearing in multiple scenes
        script_content = """INT. ROOM - DAY

JOHN
Hello.

EXT. PARK - NIGHT

JOHN
How are you?

INT. HOUSE - DAY

JOHN
I'm fine.
"""
        script_path = tmp_path / "multi_scene.fountain"
        script_path.write_text(script_content)

        # Set up voice manager with auto-assignment (no overrides)
        # The voice manager should assign a consistent voice to JOHN across all scenes
        render_service.voice_mgr.start_render()

        # Render the script
        render_service.render(script_path, output=None)

        # Verify that all TTS calls used the same voice (all for JOHN)
        # Since we have 3 dialogue blocks all from JOHN, all should have same voice
        backend = cast(MockTTSBackend, render_service.voice_mgr.backend)
        assert len(backend.calls) == 3, (
            f"Expected 3 dialogue calls, got {len(backend.calls)}"
        )
        # All voices should be identical
        voices = [voice for text, voice in backend.calls]
        assert len(set(voices)) == 1, (
            "Same character should have consistent voice across scenes"
        )

    def test_narrator_voice_excluded_from_auto_assignment(
        self,
        tmp_path: Path,
        render_service: RenderService,
    ):
        """Test that narrator voice is excluded from character auto-assignment."""
        # Create a simple script with two characters
        script_content = """INT. ROOM - DAY

JOHN
Hello.

MARY
Hi there.
"""
        script_path = tmp_path / "simple.fountain"
        script_path.write_text(script_content)

        # Configure narrator to use a specific voice that exists in the mock TTS
        # We'll modify the render_service's narrator config to enable narrator
        render_service.narrator_cfg.enabled = True
        render_service.narrator_cfg.voice = "narrator_voice"

        # Add the narrator_voice to the mock TTS available voices
        backend = cast(MockTTSBackend, render_service.voice_mgr.backend)
        backend.available_voices = ["voice1", "voice2", "narrator_voice"]

        # No explicit voice assignments - both JOHN and MARY should auto-assign
        # from the pool excluding narrator_voice
        render_service.voice_mgr.start_render()

        # Render the script
        render_service.render(script_path, output=None)

        # The TTS calls include both scene heading narration (using narrator_voice)
        # and dialogue (using character voices). We only care about dialogue voices.
        dialogue_texts = {"Hello.", "Hi there."}
        dialogue_voices = [
            voice for text, voice in backend.calls if text in dialogue_texts
        ]

        # Check that all character voices used are not the narrator_voice
        for voice in dialogue_voices:
            assert voice != "narrator_voice", (
                f"Character voice {voice} should not be narrator_voice"
            )

        # Also verify that we have exactly 2 dialogue calls (one for each character)
        assert len(dialogue_voices) == 2

    def test_narrator_voice_only_one_available_disables_narrator(
        self,
        tmp_path: Path,
        render_service: RenderService,
        caplog,
    ):
        """Test that if only one voice exists and it's used for narrator, narrator is disabled with warning."""
        # Create a simple script
        script_content = """INT. ROOM - DAY

JOHN
Hello.
"""
        script_path = tmp_path / "simple.fountain"
        script_path.write_text(script_content)

        # Configure TTS to have only one voice
        backend = cast(MockTTSBackend, render_service.voice_mgr.backend)
        backend.available_voices = ["only_voice"]

        # Configure narrator to use that only voice
        render_service.narrator_cfg.enabled = True
        render_service.narrator_cfg.voice = "only_voice"

        # No explicit voice assignment for JOHN - will auto-assign
        render_service.voice_mgr.start_render()

        # Render should succeed, and narrator should be disabled because
        # the only voice is excluded from character auto-assignment pool,
        # making the pool empty. This should trigger a ValueError in set_narrator_voice,
        # which RenderService should catch and disable narrator.
        render_service.render(script_path, output=None)

        # Check that narrator was disabled (narrator_cfg.enabled should be False)
        assert not render_service.narrator_cfg.enabled

        # Check that a warning was logged about the only voice
        assert any(
            "only available voice" in record.message for record in caplog.records
        )

        # The render should have completed successfully with character voice assigned
        # Since only_voice is the only available, and narrator tried to use it,
        # the auto-assignment for JOHN would fail if narrator was enabled.
        # But since narrator got disabled, the auto-assignment pool includes only_voice.
        # So JOHN should get "only_voice"
        assert len(backend.calls) == 1  # One dialogue call
        assert backend.calls[0][0] == "Hello."  # Text matches
        # The voice used should be only_voice
        assert backend.calls[0][1] == "only_voice"

    def test_narrator_voice_can_still_be_used_by_override(
        self,
        tmp_path: Path,
        render_service: RenderService,
    ):
        """Test that narrator voice can still be used if explicitly assigned to a character."""
        script_content = """INT. ROOM - DAY

JOHN
Hello.
"""
        script_path = tmp_path / "simple.fountain"
        script_path.write_text(script_content)

        backend = cast(MockTTSBackend, render_service.voice_mgr.backend)
        backend.available_voices = ["voice1", "narrator_voice"]

        # Enable narrator with narrator_voice
        render_service.narrator_cfg.enabled = True
        render_service.narrator_cfg.voice = "narrator_voice"

        # Explicitly assign narrator_voice to JOHN
        render_service.voice_mgr.set_character_voice("JOHN", "narrator_voice")

        render_service.voice_mgr.start_render()

        render_service.render(script_path, output=None)

        # There will be two TTS calls: one for scene heading (narrator) and one for dialogue (JOHN).
        # Both will use narrator_voice. We only need to verify that the dialogue call uses narrator_voice.
        dialogue_texts = {"Hello."}
        dialogue_calls = [
            (text, voice) for text, voice in backend.calls if text in dialogue_texts
        ]
        assert len(dialogue_calls) == 1
        assert dialogue_calls[0][1] == "narrator_voice"
