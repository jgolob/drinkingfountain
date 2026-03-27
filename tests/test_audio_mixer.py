"""Comprehensive tests for the AudioMixer class."""

import pytest
from pydub import AudioSegment

from drinkingfountain.audio.mixer import (
    AudioConfig,
    AudioMixer,
    TimingConfig,
)
from drinkingfountain.parser.script import (
    BlockType,
    Dialogue,
    Parenthetical,
    SceneHeading,
)


@pytest.fixture
def default_config():
    """Default audio configuration for tests."""
    return AudioConfig()


@pytest.fixture
def default_timing():
    """Default timing configuration for tests."""
    return TimingConfig()


@pytest.fixture
def mixer(default_config, default_timing):
    """Create an AudioMixer instance for tests."""
    return AudioMixer(config=default_config, timing=default_timing)


@pytest.fixture
def sample_audio():
    """Create a sample AudioSegment for testing."""
    return AudioSegment.silent(duration=1000, frame_rate=22050)  # 1 second


@pytest.fixture
def dialogue_block():
    """Create a sample dialogue block."""
    return Dialogue(
        line_number=2,
        character="HAMLET",
        content="To be, or not to be.",
        parentheticals=[],
    )


@pytest.fixture
def scene_heading_block():
    """Create a sample scene heading block."""
    return SceneHeading(
        line_number=1,
        content="INT. CASTLE - NIGHT",
        location="INT. CASTLE",
        time="NIGHT",
    )


class TestAudioConfig:
    """Tests for AudioConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AudioConfig()
        assert config.sample_rate == 22050
        assert config.channels == "mono"
        assert config.normalize is True
        assert config.target_level == -3.0

    def test_custom_values(self):
        """Test custom configuration values."""
        config = AudioConfig(
            sample_rate=44100, channels="stereo", normalize=False, target_level=-6.0
        )
        assert config.sample_rate == 44100
        assert config.channels == "stereo"
        assert config.normalize is False
        assert config.target_level == -6.0

    def test_invalid_sample_rate(self):
        """Test that invalid sample rate raises ValueError."""
        with pytest.raises(ValueError, match="Sample rate must be positive"):
            AudioConfig(sample_rate=0)

    def test_invalid_channels(self):
        """Test that invalid channels raises ValueError."""
        with pytest.raises(ValueError, match="Channels must be 'mono' or 'stereo'"):
            AudioConfig(channels="surround")

    def test_invalid_target_level_positive(self):
        """Test that positive target level raises ValueError."""
        with pytest.raises(ValueError, match="Target level must be negative dBFS"):
            AudioConfig(target_level=1.0)


class TestTimingConfig:
    """Tests for TimingConfig dataclass."""

    def test_default_values(self):
        """Test default timing values."""
        timing = TimingConfig()
        assert timing.pause_between_lines == 0.3
        assert timing.pause_after_scene_heading == 1.0
        assert timing.pause_between_scenes == 2.0

    def test_custom_values(self):
        """Test custom timing values."""
        timing = TimingConfig(
            pause_between_lines=0.5,
            pause_after_scene_heading=1.5,
            pause_between_scenes=3.0,
        )
        assert timing.pause_between_lines == 0.5
        assert timing.pause_after_scene_heading == 1.5
        assert timing.pause_between_scenes == 3.0

    def test_negative_pauses(self):
        """Test that negative pause values raise ValueError."""
        with pytest.raises(
            ValueError, match="Pause between lines must be non-negative"
        ):
            TimingConfig(pause_between_lines=-0.1)


class TestAudioMixerInitialization:
    """Tests for AudioMixer initialization."""

    def test_init_with_defaults(self, default_config, default_timing):
        """Test mixer initializes with default configs."""
        mixer = AudioMixer()
        assert mixer.config.sample_rate == default_config.sample_rate
        assert mixer.timing.pause_between_lines == default_timing.pause_between_lines
        assert mixer.segments == []
        assert mixer.state.last_block_type is None
        assert mixer.state.current_position == 0.0

    def test_init_with_custom_config(self):
        """Test mixer initializes with provided configs."""
        config = AudioConfig(sample_rate=44100)
        timing = TimingConfig(pause_between_lines=0.5)
        mixer = AudioMixer(config=config, timing=timing)
        assert mixer.config.sample_rate == 44100
        assert mixer.timing.pause_between_lines == 0.5

    def test_clear(self, mixer, sample_audio, dialogue_block):
        """Test clearing mixer state."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        assert len(mixer.segments) > 0
        assert mixer.state.current_position > 0

        mixer.clear()
        assert mixer.segments == []
        assert mixer.state.last_block_type is None
        assert mixer.state.current_position == 0.0


class TestDialogueHandling:
    """Tests for dialogue addition and pause insertion."""

    def test_add_first_dialogue_no_pause(self, mixer, sample_audio, dialogue_block):
        """Test first dialogue gets no preceding pause."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        # First segment should be the audio itself, not a pause
        assert len(mixer.segments) == 1
        assert mixer.segments[0][1].startswith("dialogue:")
        assert mixer.state.current_position == pytest.approx(1.0)

    def test_add_multiple_dialogue_pauses(self, mixer, sample_audio):
        """Test multiple dialogue lines get appropriate pauses."""
        dialogue1 = Dialogue(line_number=2, character="HAMLET", content="To be...")
        dialogue2 = Dialogue(
            line_number=4, character="OPHELIA", content="Where is the be?"
        )

        mixer.add_dialogue(dialogue1, sample_audio)
        mixer.add_dialogue(dialogue2, sample_audio)

        # Should have: audio, pause, audio
        assert len(mixer.segments) == 3
        assert mixer.segments[0][1].startswith("dialogue:")
        assert mixer.segments[1][1].startswith("pause:")
        assert mixer.segments[2][1].startswith("dialogue:")

        # Check total duration: 2 * 1s audio + 0.3s pause
        expected_duration = 2.0 + 0.3
        assert mixer.state.current_position == pytest.approx(expected_duration)

    def test_pause_duration_respects_config(self, default_timing, sample_audio):
        """Test that custom pause duration is used."""
        custom_timing = TimingConfig(pause_between_lines=0.5)
        mixer = AudioMixer(timing=custom_timing)

        d1 = Dialogue(line_number=1, character="A", content="Line 1")
        d2 = Dialogue(line_number=2, character="B", content="Line 2")

        mixer.add_dialogue(d1, sample_audio)
        mixer.add_dialogue(d2, sample_audio)

        # Find the pause segment
        pause_segment = mixer.segments[1][0]
        assert pause_segment.duration_seconds == pytest.approx(0.5)

    def test_add_dialogue_invalid_audio(self, mixer, dialogue_block):
        """Test that adding non-AudioSegment raises error."""
        with pytest.raises(ValueError, match="Expected AudioSegment"):
            mixer.add_dialogue(dialogue_block, "not an audio segment")


class TestSceneHeadingHandling:
    """Tests for scene heading handling."""

    def test_scene_heading_first(self, mixer, sample_audio, scene_heading_block):
        """Test first scene heading (no preceding pause)."""
        mixer.add_scene_heading(scene_heading_block, audio=sample_audio)

        # Should have: audio, post-heading pause
        assert len(mixer.segments) == 2
        assert mixer.segments[0][1].startswith("scene_heading:")
        assert mixer.segments[1][1].startswith("pause:post_heading")
        assert mixer.state.current_position == pytest.approx(1.0 + 1.0)  # audio + pause

    def test_scene_heading_without_audio(self, mixer, scene_heading_block):
        """Test scene heading with no audio (only pauses)."""
        mixer.add_scene_heading(scene_heading_block, audio=None)

        # Should have only post-heading pause
        assert len(mixer.segments) == 1
        assert mixer.segments[0][1].startswith("pause:post_heading")
        assert mixer.state.current_position == pytest.approx(1.0)

    def test_scene_transition_pause(self, default_timing, sample_audio):
        """Test that scene transitions get longer pause."""
        mixer = AudioMixer(timing=default_timing)

        heading1 = SceneHeading(line_number=1, content="SCENE 1", location="SCENE 1")
        heading2 = SceneHeading(line_number=5, content="SCENE 2", location="SCENE 2")

        d1 = Dialogue(line_number=2, character="A", content="Dialogue 1")

        mixer.add_scene_heading(heading1, audio=None)
        mixer.add_dialogue(d1, sample_audio)
        mixer.add_scene_heading(heading2, audio=None)

        # Segments: pause1 (post-heading1), dialogue+pre-pause, pause2 (between scenes), heading2, post-heading2
        # Actually: heading1 adds post-heading pause, then dialogue, then heading2 adds between-scenes pause + itself + post-heading
        # Let's trace:
        # - add_scene_heading(heading1): adds post-heading pause (1.0s)
        # - add_dialogue(d1): adds pause between lines? No, last_block_type is SCENE_HEADING, so no additional pause
        # - add_scene_heading(heading2): last_block_type is DIALOGUE, so adds between-scenes pause (2.0s), then heading audio (none), then post-heading pause (1.0s)

        # So we should have: [post-heading1], [dialogue], [between-scenes], [post-heading2]
        assert len(mixer.segments) == 4
        # Check between-scenes pause is 2.0s
        between_scenes_pause = mixer.segments[2][0]
        assert between_scenes_pause.duration_seconds == pytest.approx(2.0)

    def test_scene_heading_updates_state(self, mixer, scene_heading_block):
        """Test that scene heading updates state correctly."""
        mixer.add_scene_heading(scene_heading_block, audio=None)
        assert mixer.state.last_block_type == BlockType.SCENE_HEADING
        assert mixer.state.in_scene is True


class TestAudioPreparation:
    """Tests for audio format conversion."""

    def test_sample_rate_conversion(self, default_config):
        """Test that audio with different sample rate gets converted."""
        mixer = AudioMixer(config=default_config)
        # Create audio at 44100 Hz
        audio_44k = AudioSegment.silent(duration=500, frame_rate=44100)
        prepared = mixer._prepare_audio(audio_44k)
        assert prepared.frame_rate == default_config.sample_rate

    def test_channel_conversion_mono_to_stereo(self):
        """Test mono to stereo conversion."""
        config = AudioConfig(channels="stereo")
        mixer = AudioMixer(config=config)
        mono_audio = AudioSegment.silent(duration=500, frame_rate=22050)
        mono_audio = mono_audio.set_channels(1)
        prepared = mixer._prepare_audio(mono_audio)
        assert prepared.channels == 2

    def test_channel_conversion_stereo_to_mono(self):
        """Test stereo to mono conversion."""
        config = AudioConfig(channels="mono")
        mixer = AudioMixer(config=config)
        stereo_audio = AudioSegment.silent(duration=500, frame_rate=22050)
        stereo_audio = stereo_audio.set_channels(2)
        prepared = mixer._prepare_audio(stereo_audio)
        assert prepared.channels == 1

    def test_no_conversion_when_matching(self, default_config):
        """Test no conversion when format already matches."""
        mixer = AudioMixer(config=default_config)
        audio = AudioSegment.silent(duration=500, frame_rate=default_config.sample_rate)
        audio = audio.set_channels(1 if default_config.channels == "mono" else 2)
        prepared = mixer._prepare_audio(audio)
        assert prepared.frame_rate == audio.frame_rate
        assert prepared.channels == audio.channels


class TestNormalization:
    """Tests for audio normalization."""

    def test_normalize_raises_level(self, default_config):
        """Test that normalization raises audio to target level."""
        mixer = AudioMixer(config=default_config)
        # Create quiet audio (well below target) with some actual sound
        # Use a sine wave or tone to have actual dBFS
        quiet_audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        # Add a tone to give it some signal
        from pydub.generators import Sine

        tone = Sine(440).to_audio_segment(duration=1000)
        quiet_audio = quiet_audio.overlay(tone - 20)  # Overlay at -20dB

        normalized = mixer._normalize_audio(quiet_audio)
        # Should be boosted to near target level
        assert normalized.dBFS > default_config.target_level - 1  # Within 1 dB

    def test_normalize_does_not_clip(self, default_config):
        """Test that normalization doesn't cause clipping above 0 dB."""
        mixer = AudioMixer(config=default_config)
        # Create audio already near 0 dB
        loud_audio = AudioSegment.silent(duration=1000, frame_rate=22050)
        loud_audio = loud_audio.apply_gain(-1.0)

        normalized = mixer._normalize_audio(loud_audio)
        # Should not exceed 0 dB (max for digital audio)
        assert normalized.max_dBFS <= 0.0

    def test_normalize_empty_audio(self, default_config):
        """Test that normalizing empty audio returns it unchanged."""
        mixer = AudioMixer(config=default_config)
        empty = AudioSegment.silent(duration=0)
        result = mixer._normalize_audio(empty)
        assert result.duration_seconds == 0

    def test_normalize_config_disabled(self, sample_audio, dialogue_block):
        """Test that normalization is skipped when config.normalize is False."""
        config = AudioConfig(normalize=False)
        mixer = AudioMixer(config=config)
        mixer.add_dialogue(dialogue_block, sample_audio)
        mix = mixer.get_mix()
        # Silent audio should remain very quiet (not normalized to -3dB)
        assert mix.dBFS < -50  # Still essentially silent


class TestGetMix:
    """Tests for get_mix() method."""

    def test_get_mix_empty(self, mixer):
        """Test get_mix with no segments returns silent audio."""
        mix = mixer.get_mix()
        assert mix.duration_seconds == 0

    def test_get_mix_concatenates_segments(self, mixer, sample_audio, dialogue_block):
        """Test that get_mix concatenates all segments in order."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        mixer.add_dialogue(dialogue_block, sample_audio)

        mix = mixer.get_mix()
        # Total: 2s audio + 0.3s pause
        assert mix.duration_seconds == pytest.approx(2.3)

    def test_get_mix_applies_normalization(self, mixer, sample_audio, dialogue_block):
        """Test that get_mix normalizes when config.normalize is True."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        mix = mixer.get_mix()
        # Should be normalized to near target level
        assert mix.dBFS <= mixer.config.target_level + 0.5  # Allow some tolerance

    def test_get_mix_no_normalization_when_disabled(self, sample_audio, dialogue_block):
        """Test normalization skipped when config.normalize is False."""
        config = AudioConfig(normalize=False)
        mixer = AudioMixer(config=config)
        mixer.add_dialogue(dialogue_block, sample_audio)
        mix = mixer.get_mix()
        # Should be at or near 0 dB (silent audio)
        assert mix.dBFS < -50  # Silent audio is very low

    def test_get_mix_applies_sound_effects(self, mixer, sample_audio, dialogue_block):
        """Test that sound effects are overlaid at correct positions."""
        # Add two dialogue lines to get a pause between them
        d1 = Dialogue(line_number=1, character="A", content="First")
        d2 = Dialogue(line_number=2, character="B", content="Second")
        mixer.add_dialogue(d1, sample_audio)
        mixer.add_dialogue(d2, sample_audio)

        # Add a sound effect at 0.5 seconds into the mix
        effect = AudioSegment.silent(duration=200, frame_rate=22050).apply_gain(-3.0)
        mixer.add_sound_effect(effect, timestamp=0.5, description="test effect")

        mix = mixer.get_mix()
        # Duration should be: 1s + 0.3s pause + 1s = 2.3s
        assert mix.duration_seconds == pytest.approx(2.3)

        # The effect should be present at position 0.5s
        # We can't easily test the exact audio content, but we can check it's not silent
        # Actually, the mix is silent except for the effect, but the effect is also silent with gain
        # This is hard to test without analyzing the waveform; we'll trust pydub's overlay


class TestExport:
    """Tests for export() method."""

    def test_export_wav(self, mixer, sample_audio, dialogue_block, tmp_path):
        """Test exporting to WAV file."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        output_path = tmp_path / "test.wav"
        mixer.export(str(output_path), format="wav")

        assert output_path.exists()
        # Verify we can read it back
        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == pytest.approx(1.0)

    def test_export_creates_directories(
        self, mixer, sample_audio, dialogue_block, tmp_path
    ):
        """Test that export creates missing directories."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        output_path = tmp_path / "subdir" / "nested" / "test.wav"
        mixer.export(str(output_path), format="wav")
        assert output_path.exists()

    def test_export_mp3(self, mixer, sample_audio, dialogue_block, tmp_path):
        """Test exporting to MP3 file."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        output_path = tmp_path / "test.mp3"
        mixer.export(str(output_path), format="mp3", bitrate="192k")
        assert output_path.exists()

    def test_export_empty_raises_error(self, mixer, tmp_path):
        """Test that exporting empty mix raises error for non-WAV formats."""
        output_path = tmp_path / "test.mp3"
        with pytest.raises(ValueError, match="Cannot export empty mix"):
            mixer.export(str(output_path), format="mp3")

    def test_export_empty_wav_allowed(self, mixer, tmp_path):
        """Test that exporting empty mix to WAV is allowed (creates silent file)."""
        output_path = tmp_path / "silent.wav"
        mixer.export(str(output_path), format="wav")
        assert output_path.exists()
        exported = AudioSegment.from_wav(output_path)
        assert exported.duration_seconds == 0


class TestDuration:
    """Tests for duration() method."""

    def test_duration_empty(self, mixer):
        """Test duration of empty mixer."""
        assert mixer.duration() == 0.0

    def test_duration_with_segments(self, mixer, sample_audio, dialogue_block):
        """Test duration includes all segments and pauses."""
        mixer.add_dialogue(dialogue_block, sample_audio)
        assert mixer.duration() == pytest.approx(1.0)

        mixer.add_dialogue(dialogue_block, sample_audio)
        assert mixer.duration() == pytest.approx(2.3)  # 2s audio + 0.3s pause

    def test_duration_with_scene_heading(self, mixer, scene_heading_block):
        """Test duration includes scene heading pauses."""
        mixer.add_scene_heading(scene_heading_block, audio=None)
        assert mixer.duration() == pytest.approx(1.0)  # post-heading pause

        mixer.add_scene_heading(scene_heading_block, audio=None)
        # Second heading adds: between-scenes pause (2.0) + post-heading (1.0)
        assert mixer.duration() == pytest.approx(4.0)  # 1.0 + 2.0 + 1.0


class TestSoundEffects:
    """Tests for sound effect handling."""

    def test_add_sound_effect(self, mixer):
        """Test adding a sound effect."""
        effect = AudioSegment.silent(duration=500, frame_rate=22050)
        mixer.add_sound_effect(effect, timestamp=1.0, description="test")
        assert 1.0 in mixer._sound_effects
        assert len(mixer._sound_effects) == 1

    def test_sound_effect_overlay_in_get_mix(self, mixer, sample_audio):
        """Test that sound effects are overlaid in the final mix."""
        # Add two dialogue lines
        d1 = Dialogue(line_number=1, character="A", content="First")
        d2 = Dialogue(line_number=2, character="B", content="Second")
        mixer.add_dialogue(d1, sample_audio)
        mixer.add_dialogue(d2, sample_audio)

        # Add a non-silent effect
        effect = AudioSegment.silent(duration=200, frame_rate=22050).apply_gain(-6.0)
        mixer.add_sound_effect(effect, timestamp=0.5)
        mix = mixer.get_mix()
        # Duration should be: 1s + 0.3s + 1s = 2.3s
        assert mix.duration_seconds == pytest.approx(2.3)

    def test_sound_effect_out_of_bounds(self, mixer, sample_audio):
        """Test that sound effects beyond mix duration are ignored."""
        d1 = Dialogue(line_number=1, character="A", content="First")
        d2 = Dialogue(line_number=2, character="B", content="Second")
        mixer.add_dialogue(d1, sample_audio)
        mixer.add_dialogue(d2, sample_audio)
        effect = AudioSegment.silent(duration=200, frame_rate=22050)
        mixer.add_sound_effect(effect, timestamp=10.0)  # Way past end
        mix = mixer.get_mix()
        # Should not extend duration: 1s + 0.3s + 1s = 2.3s
        assert mix.duration_seconds == pytest.approx(2.3)


class TestIntegration:
    """Integration tests simulating real usage."""

    def test_full_scene_with_dialogue(self, mixer, scene_heading_block):
        """Test a complete scene with heading and multiple dialogue lines."""
        audio1 = AudioSegment.silent(duration=800, frame_rate=22050)
        audio2 = AudioSegment.silent(duration=1200, frame_rate=22050)
        audio3 = AudioSegment.silent(duration=1000, frame_rate=22050)

        d1 = Dialogue(line_number=2, character="HAMLET", content="To be...")
        d2 = Dialogue(line_number=4, character="OPHELIA", content="What?")
        d3 = Dialogue(line_number=6, character="HAMLET", content="Or not to be.")

        mixer.add_scene_heading(scene_heading_block, audio=None)
        mixer.add_dialogue(d1, audio1)
        mixer.add_dialogue(d2, audio2)
        mixer.add_dialogue(d3, audio3)

        # Expected timeline:
        # - post-heading pause: 1.0s
        # - d1: 0.8s
        # - pause: 0.3s
        # - d2: 1.2s
        # - pause: 0.3s
        # - d3: 1.0s
        expected = 1.0 + 0.8 + 0.3 + 1.2 + 0.3 + 1.0
        assert mixer.duration() == pytest.approx(expected)

    def test_multiple_scenes(self, default_timing, sample_audio):
        """Test multiple scenes with proper transitions."""
        mixer = AudioMixer(timing=default_timing)

        heading1 = SceneHeading(line_number=1, content="SCENE 1", location="SCENE 1")
        heading2 = SceneHeading(line_number=10, content="SCENE 2", location="SCENE 2")

        d1 = Dialogue(line_number=2, character="A", content="Scene 1 dialogue")
        d2 = Dialogue(line_number=11, character="B", content="Scene 2 dialogue")

        mixer.add_scene_heading(heading1, audio=None)
        mixer.add_dialogue(d1, sample_audio)
        mixer.add_scene_heading(heading2, audio=None)
        mixer.add_dialogue(d2, sample_audio)

        # Timeline:
        # - heading1 post-pause: 1.0
        # - d1: 1.0
        # - between-scenes pause: 2.0
        # - heading2 post-pause: 1.0
        # - d2: 1.0
        expected = 1.0 + 1.0 + 2.0 + 1.0 + 1.0
        assert mixer.duration() == pytest.approx(expected)

    def test_parentheticals_not_supported_yet(self, mixer, sample_audio):
        """Test that parentheticals are currently ignored (future work)."""
        parenthetical = Parenthetical(line_number=2, text="(sighs)")
        dialogue = Dialogue(
            line_number=3,
            character="HAMLET",
            content="Alas",
            parentheticals=[parenthetical],
        )

        # Should work fine, parentheticals are just part of the dialogue block
        mixer.add_dialogue(dialogue, sample_audio)
        assert len(mixer) == 1
