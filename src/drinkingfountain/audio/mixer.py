"""Audio mixing engine for drinkingfountain.

This module provides the AudioMixer class which combines audio segments
with configurable pauses, normalization, and export capabilities.
"""

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydub import AudioSegment

from drinkingfountain.parser.script import Action, Block, BlockType, Dialogue


class ChannelMode(Enum):
    """Audio channel configuration."""

    MONO = "mono"
    STEREO = "stereo"


@dataclass
class AudioConfig:
    """Configuration for audio output.

    Attributes:
        sample_rate: Target sample rate in Hz (default: 22050)
        channels: Channel mode - "mono" or "stereo" (default: "mono")
        normalize: Whether to normalize the final mix (default: True)
        target_level: Target loudness level in dBFS (default: -3.0)
            Typically ranges from -6.0 to -1.0 dB for broadcast safety.
    """

    sample_rate: int = 22050
    channels: str = "mono"
    normalize: bool = True
    target_level: float = -3.0

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.sample_rate <= 0:
            raise ValueError(f"Sample rate must be positive, got {self.sample_rate}")
        if self.channels not in ("mono", "stereo"):
            raise ValueError(
                f"Channels must be 'mono' or 'stereo', got {self.channels}"
            )
        if self.target_level > 0:
            raise ValueError(
                f"Target level must be negative dBFS, got {self.target_level}"
            )


@dataclass
class TimingConfig:
    """Configuration for timing and pauses.

    Attributes:
        pause_between_lines: Pause between consecutive dialogue lines in seconds (default: 0.3)
        pause_after_scene_heading: Pause after a scene heading in seconds (default: 1.0)
        pause_between_scenes: Pause between scenes (after heading, before next dialogue) in seconds (default: 2.0)
    """

    pause_between_lines: float = 0.3
    pause_after_scene_heading: float = 1.0
    pause_between_scenes: float = 2.0

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.pause_between_lines < 0:
            raise ValueError(
                f"Pause between lines must be non-negative, got {self.pause_between_lines}"
            )
        if self.pause_after_scene_heading < 0:
            raise ValueError(
                f"Pause after scene heading must be non-negative, got {self.pause_after_scene_heading}"
            )
        if self.pause_between_scenes < 0:
            raise ValueError(
                f"Pause between scenes must be non-negative, got {self.pause_between_scenes}"
            )


@dataclass
class MixerState:
    """Internal state tracking for the AudioMixer.

    Tracks the current position in the timeline and the type of the last
    non-silence block to determine appropriate pause durations.
    """

    last_block_type: BlockType | None = None
    current_position: float = 0.0  # Position in seconds
    in_scene: bool = False  # Whether we're currently inside a scene (after heading)


class AudioMixer:
    """Mixes audio segments with configurable pauses and normalization.

    The AudioMixer accepts dialogue blocks with their corresponding audio
    segments and automatically inserts appropriate pauses based on script
    structure. It handles sample rate conversion, channel mixing, and
    loudness normalization.

    Example:
        >>> from pydub import AudioSegment
        >>> from drinkingfountain.audio.mixer import AudioMixer, AudioConfig, TimingConfig
        >>>
        >>> mixer = AudioMixer(AudioConfig(), TimingConfig())
        >>> # Add dialogue with audio
        >>> mixer.add_dialogue(dialogue_block, audio_segment)
        >>>
        >>> # Export the final mix
        >>> mixer.export("output.wav")

    Attributes:
        config: Audio output configuration
        timing: Timing and pause configuration
        segments: List of (AudioSegment, description) tuples in chronological order
        state: Current mixer state
    """

    def __init__(
        self,
        config: AudioConfig | None = None,
        timing: TimingConfig | None = None,
    ) -> None:
        """Initialize the AudioMixer.

        Args:
            config: Audio configuration. If None, uses defaults.
            timing: Timing configuration. If None, uses defaults.
        """
        self.config = config or AudioConfig()
        self.timing = timing or TimingConfig()
        self.segments: list[tuple[AudioSegment, str]] = []
        self.state = MixerState()
        self._sound_effects: dict[float, AudioSegment] = {}  # Position -> effect

    def add_dialogue(
        self,
        dialogue: Dialogue,
        audio: AudioSegment,
    ) -> None:
        """Add a dialogue line with its audio to the mix.

        This method automatically inserts the appropriate pause before the
        dialogue based on what preceded it (scene heading, previous dialogue,
        scene change, etc.).

        Args:
            dialogue: The dialogue block containing the text and character.
            audio: The audio segment for this dialogue line. Should be at
                least the same sample rate as the mixer config, or it will
                be converted.

        Raises:
            ValueError: If audio is not a valid AudioSegment.
        """
        if not isinstance(audio, AudioSegment):
            raise ValueError(f"Expected AudioSegment, got {type(audio)}")

        # Determine required pause based on context
        pause_duration = self._calculate_pause_for_block(dialogue)

        # Convert audio to target sample rate and channels if needed
        audio = self._prepare_audio(audio)

        # Insert pause if needed
        if pause_duration > 0:
            pause = AudioSegment.silent(
                duration=int(pause_duration * 1000),  # Convert to ms
                frame_rate=self.config.sample_rate,
            )
            if self.config.channels == ChannelMode.MONO.value:
                pause = pause.set_channels(1)
            else:
                pause = pause.set_channels(2)
            self.segments.append((pause, f"pause:{pause_duration:.2f}s"))
            self.state.current_position += pause_duration

        # Add the dialogue audio
        self.segments.append((audio, f"dialogue:{dialogue.character}"))
        self.state.current_position += audio.duration_seconds
        self.state.last_block_type = BlockType.DIALOGUE
        self.state.in_scene = True

    def add_scene_heading(
        self,
        heading: Block,
        audio: AudioSegment | None = None,
        pause_after: float | None = None,
    ) -> None:
        """Add a scene heading to the mix.

        If audio is provided, it will be added (typically a spoken scene
        description). Otherwise, only the pause after the heading is
        accounted for in subsequent timing.

        Args:
            heading: The scene heading block.
            audio: Optional audio segment for the heading itself.
            pause_after: Optional custom pause duration in seconds after the heading.
                If None, uses self.timing.pause_after_scene_heading.
        """
        # Determine if this is a new scene (transition from another scene)
        is_scene_transition = self.state.last_block_type == BlockType.SCENE_HEADING or (
            self.state.last_block_type is not None
            and self.state.last_block_type != BlockType.SCENE_HEADING
        )

        # Insert pause before heading if transitioning from a previous scene
        if is_scene_transition and self.state.last_block_type is not None:
            pause_duration = self.timing.pause_between_scenes
            pause = AudioSegment.silent(
                duration=int(pause_duration * 1000),
                frame_rate=self.config.sample_rate,
            )
            if self.config.channels == ChannelMode.MONO.value:
                pause = pause.set_channels(1)
            else:
                pause = pause.set_channels(2)
            self.segments.append(
                (pause, f"pause:scene_transition:{pause_duration:.2f}s")
            )
            self.state.current_position += pause_duration

        # Add heading audio if provided
        if audio is not None:
            audio = self._prepare_audio(audio)
            self.segments.append((audio, f"scene_heading:{heading.content[:30]}..."))
            self.state.current_position += audio.duration_seconds

        # Add post-heading pause
        pause_duration = (
            pause_after
            if pause_after is not None
            else self.timing.pause_after_scene_heading
        )
        pause = AudioSegment.silent(
            duration=int(pause_duration * 1000),
            frame_rate=self.config.sample_rate,
        )
        if self.config.channels == ChannelMode.MONO.value:
            pause = pause.set_channels(1)
        else:
            pause = pause.set_channels(2)
        self.segments.append((pause, f"pause:post_heading:{pause_duration:.2f}s"))
        self.state.current_position += pause_duration

        self.state.last_block_type = BlockType.SCENE_HEADING
        self.state.in_scene = True

    def add_sound_effect(
        self,
        effect: AudioSegment,
        timestamp: float,
        description: str = "",
    ) -> None:
        """Add a sound effect at a specific timestamp.

        The sound effect will be overlaid on the existing mix at the given
        timestamp during export. This is a placeholder for future expansion.

        Args:
            effect: The sound effect audio segment.
            timestamp: Time in seconds where the effect should start.
            description: Optional description for debugging.
        """
        effect = self._prepare_audio(effect)
        self._sound_effects[timestamp] = effect
        # Note: We don't add to self.segments because effects are overlaid later

    def add_narrative(
        self,
        block: Action,
        audio: AudioSegment,
        pause_before: float = 0.5,
        pause_after: float = 0.3,
    ) -> None:
        """Add a narrative segment (stage directions) with configurable pauses.

        This method is used for reading Action blocks (stage directions) with
        the narrator voice. It allows specifying custom pause durations before
        and after the narrative.

        Args:
            block: The Action block being narrated.
            audio: The audio segment for the narrative text.
            pause_before: Pause duration in seconds before the narrative (default: 0.5)
            pause_after: Pause duration in seconds after the narrative (default: 0.3)

        Raises:
            ValueError: If audio is not a valid AudioSegment.
        """
        if not isinstance(audio, AudioSegment):
            raise ValueError(f"Expected AudioSegment, got {type(audio)}")

        # Add pre-pause if needed
        if pause_before > 0:
            pause = AudioSegment.silent(
                duration=int(pause_before * 1000),  # Convert to ms
                frame_rate=self.config.sample_rate,
            )
            if self.config.channels == ChannelMode.MONO.value:
                pause = pause.set_channels(1)
            else:
                pause = pause.set_channels(2)
            self.segments.append((pause, f"pause:before_narrative:{pause_before:.2f}s"))
            self.state.current_position += pause_before

        # Add the narrative audio
        audio = self._prepare_audio(audio)
        self.segments.append((audio, f"narrative:{block.content[:30]}..."))
        self.state.current_position += audio.duration_seconds

        # Add post-pause if needed
        if pause_after > 0:
            pause = AudioSegment.silent(
                duration=int(pause_after * 1000),  # Convert to ms
                frame_rate=self.config.sample_rate,
            )
            if self.config.channels == ChannelMode.MONO.value:
                pause = pause.set_channels(1)
            else:
                pause = pause.set_channels(2)
            self.segments.append((pause, f"pause:after_narrative:{pause_after:.2f}s"))
            self.state.current_position += pause_after

        self.state.last_block_type = BlockType.ACTION
        self.state.in_scene = True

    def _calculate_pause_for_block(self, block: Block) -> float:
        """Calculate the appropriate pause duration before adding this block.

        Args:
            block: The block about to be added.

        Returns:
            Pause duration in seconds.
        """
        if self.state.last_block_type is None:
            # First block, no pause
            return 0.0

        # Check if we're transitioning to a new scene
        # This would require knowing if the current block belongs to a different scene
        # For now, we rely on explicit scene heading calls to mark scene boundaries

        if self.state.last_block_type == BlockType.SCENE_HEADING:
            # After a scene heading, we already added the post-heading pause
            # So between heading and first dialogue, no additional pause
            return 0.0

        # Default: pause between dialogue lines
        return self.timing.pause_between_lines

    def _prepare_audio(self, audio: AudioSegment) -> AudioSegment:
        """Prepare audio segment to match mixer configuration.

        Handles sample rate conversion and channel conversion.

        Args:
            audio: Input audio segment.

        Returns:
            Prepared audio segment matching config.
        """
        # Convert sample rate if needed
        if audio.frame_rate != self.config.sample_rate:
            audio = audio.set_frame_rate(self.config.sample_rate)

        # Convert channels if needed
        current_channels = audio.channels
        target_channels = 1 if self.config.channels == ChannelMode.MONO.value else 2
        if current_channels != target_channels:
            audio = audio.set_channels(target_channels)

        return audio

    def _normalize_audio(self, audio: AudioSegment) -> AudioSegment:
        """Normalize audio to target dBFS level.

        Args:
            audio: Input audio segment.

        Returns:
            Normalized audio segment.
        """
        if audio.dBFS == float("-inf"):
            return audio  # Empty segment, nothing to normalize

        # Calculate gain needed to reach target level
        gain = self.config.target_level - audio.dBFS
        return audio.apply_gain(gain)

    def clear(self) -> None:
        """Clear all segments and reset state."""
        self.segments.clear()
        self._sound_effects.clear()
        self.state = MixerState()

    def get_mix(self) -> AudioSegment:
        """Get the mixed audio as a single AudioSegment.

        This method concatenates all added segments and applies sound effects
        by overlaying them at their designated timestamps.

        Returns:
            The complete mixed audio segment.
        """
        if not self.segments:
            return AudioSegment.silent(
                duration=0,
                frame_rate=self.config.sample_rate,
            )

        # Concatenate all segments in order
        mix = AudioSegment.empty()
        for segment, _ in self.segments:
            mix += segment

        # Apply sound effects by overlaying
        for timestamp, effect in self._sound_effects.items():
            # Convert timestamp to milliseconds
            start_ms = int(timestamp * 1000)
            if start_ms < len(mix):
                mix = mix.overlay(effect, position=start_ms)

        # Normalize if configured
        if self.config.normalize:
            mix = self._normalize_audio(mix)

        return mix

    def export(
        self,
        filepath: str | Path,
        format: str = "wav",
        bitrate: str | None = None,
        parameters: list[Any] | None = None,
    ) -> None:
        """Export the mixed audio to a file.

        Args:
            filepath: Output file path.
            format: Export format (e.g., "wav", "mp3"). Default: "wav"
            bitrate: Optional bitrate for compressed formats (e.g., "192k").
            parameters: Additional format-specific parameters.

        Raises:
            ValueError: If no segments have been added and format requires audio.
            IOError: If file cannot be written.
        """
        mix = self.get_mix()

        if len(mix) == 0 and format != "wav":
            # Empty mix, but WAV can handle it
            raise ValueError("Cannot export empty mix (no segments added)")

        # Ensure parent directory exists
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Export with appropriate parameters
        mix.export(
            out_f=filepath,
            format=format,
            bitrate=bitrate,
            parameters=parameters,
        )

    def duration(self) -> float:
        """Get the total duration of the current mix in seconds.

        Returns:
            Total duration in seconds.
        """
        return self.state.current_position

    def __len__(self) -> int:
        """Return the number of segments added (excluding sound effects)."""
        return len(self.segments)


class StreamingWAVWriter:
    """Stream audio to a WAV file incrementally to reduce memory usage.

    This class writes WAV audio data as it becomes available, maintaining
    only a running duration count rather than storing all audio in memory.

    The WAV header is written with placeholder values initially, then updated
    with correct sizes in finalize().

    Example:
        >>> writer = StreamingWAVWriter(sample_rate=22050, channels=1, sample_width=2)
        >>> writer.write_audio(audio_segment1)
        >>> writer.write_audio(audio_segment2)
        >>> writer.finalize()  # Closes file and updates header
    """

    def __init__(
        self, filepath: str | Path, sample_rate: int, channels: int, sample_width: int
    ) -> None:
        """Initialize the streaming WAV writer.

        Args:
            filepath: Output WAV file path.
            sample_rate: Sample rate in Hz.
            channels: Number of channels (1 for mono, 2 for stereo).
            sample_width: Sample width in bytes (typically 2 for 16-bit audio).
        """
        self.filepath = Path(filepath)
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self._total_bytes = 0
        self._file = None

    def __enter__(self) -> "StreamingWAVWriter":
        """Context manager entry: open file and write WAV header placeholder."""
        self._file = open(self.filepath, "wb")
        self._write_wav_header_placeholder()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit: finalize if not already done."""
        if self._file and not self._file.closed:
            self.finalize()

    def _write_wav_header_placeholder(self) -> None:
        """Write a 44-byte WAV header with placeholder sizes."""
        import struct

        if self._file is None:
            raise RuntimeError("Writer not opened")
        # RIFF header
        self._file.write(b"RIFF")
        self._file.write(struct.pack("<I", 0))  # Placeholder for file size - 8
        self._file.write(b"WAVE")

        # fmt chunk
        self._file.write(b"fmt ")
        self._file.write(
            struct.pack(
                "<IHHIIHH",
                16,
                1,
                self.channels,
                self.sample_rate,
                self.sample_rate * self.channels * self.sample_width,
                self.channels * self.sample_width,
                self.sample_width * 8,
            )
        )

        # data chunk
        self._file.write(b"data")
        self._file.write(struct.pack("<I", 0))  # Placeholder for data size

    def write_audio(self, audio: "AudioSegment") -> None:
        """Write an audio segment to the file.

        Args:
            audio: AudioSegment to write. Should match the writer's sample rate
                  and channels (will be converted if needed).

        Raises:
            ValueError: If audio is not an AudioSegment.
            RuntimeError: If writer is closed.
        """
        from pydub import AudioSegment

        if not isinstance(audio, AudioSegment):
            raise ValueError(f"Expected AudioSegment, got {type(audio)}")

        if self._file is None or self._file.closed:
            raise RuntimeError("Writer is closed")
        assert self._file is not None  # for type checker

        # Ensure audio matches output format
        if audio.frame_rate != self.sample_rate:
            audio = audio.set_frame_rate(self.sample_rate)
        if audio.channels != self.channels:
            audio = audio.set_channels(self.channels)

        # Write raw audio data
        self._file.write(audio.raw_data)
        self._total_bytes += len(audio.raw_data)

    def finalize(self) -> None:
        """Update WAV header with correct sizes and close the file.

        This method seeks back to fix the placeholder values in the header
        with the actual file size and data size, then closes the file.
        """
        if self._file is None or self._file.closed:
            return
        assert self._file is not None  # for type checker

        import struct

        # Calculate sizes
        file_size = self._total_bytes + 44  # Total file size
        data_size = self._total_bytes

        # Seek to file size position (byte 4)
        self._file.seek(4)
        self._file.write(struct.pack("<I", file_size - 8))

        # Seek to data size position (byte 40)
        self._file.seek(40)
        self._file.write(struct.pack("<I", data_size))

        self._file.close()
        self._file = None


class StreamingAudioPlayer:
    """Stream audio to the audio device incrementally using simpleaudio.

    This class plays audio chunks as they become available, reducing memory
    usage compared to building the complete mix before playback.

    Playback is synchronous - each write_audio() call blocks until that chunk
    has finished playing. This avoids overlapping playback and potential
    concurrency issues.

    Example:
        >>> player = StreamingAudioPlayer(sample_rate=22050, channels=1, sample_width=2)
        >>> player.write_audio(audio_segment1)  # Blocks until finished
        >>> player.write_audio(audio_segment2)  # Blocks until finished
        >>> player.finalize()  # Cleanup
    """

    def __init__(self, sample_rate: int, channels: int, sample_width: int) -> None:
        """Initialize the streaming audio player.

        Args:
            sample_rate: Sample rate in Hz.
            channels: Number of channels (1 for mono, 2 for stereo).
            sample_width: Sample width in bytes (typically 2 for 16-bit audio).
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self._simpleaudio = None
        self._all_played = False

    def _ensure_simpleaudio(self) -> None:
        """Lazy import simpleaudio and raise helpful error if unavailable."""
        if self._simpleaudio is not None:
            return
        try:
            import simpleaudio as sa

            self._simpleaudio = sa
        except ImportError as err:
            raise ImportError(
                "Audio playback requires 'simpleaudio'. Install with:\n"
                "  pip install simpleaudio"
            ) from err

    def write_audio(self, audio: "AudioSegment") -> None:
        """Write an audio segment to be played.

        This method blocks until the audio has finished playing.

        Args:
            audio: AudioSegment to play. Should match the player's sample rate
                  and channels (will be converted if needed).

        Raises:
            ValueError: If audio is not an AudioSegment.
            RuntimeError: If finalize() has already been called.
        """
        from pydub import AudioSegment

        if not isinstance(audio, AudioSegment):
            raise ValueError(f"Expected AudioSegment, got {type(audio)}")

        if self._all_played:
            raise RuntimeError("Cannot write audio after finalize() has been called")

        self._ensure_simpleaudio()
        assert self._simpleaudio is not None  # for type checker

        # Ensure audio matches output format
        if audio.frame_rate != self.sample_rate:
            audio = audio.set_frame_rate(self.sample_rate)
        if audio.channels != self.channels:
            audio = audio.set_channels(self.channels)

        # Play the audio buffer and wait for completion
        play_obj = self._simpleaudio.play_buffer(
            audio.raw_data,
            num_channels=audio.channels,
            bytes_per_sample=audio.sample_width,
            sample_rate=audio.frame_rate,
        )
        play_obj.wait_done()
        # Small delay to ensure audio device is ready for next buffer
        # This prevents issues where only the first scene plays on some systems
        time.sleep(0.1)

    def finalize(self) -> None:
        """Finalize the player.

        For StreamingAudioPlayer, all audio is already played by the time
        write_audio returns, so this is just a marker that no more audio
        will be written.
        """
        self._all_played = True
