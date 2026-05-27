"""Business logic services for drinkingfountain.

This module contains service classes that encapsulate core functionality
for rendering scripts and managing voices, separating them from CLI concerns.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pydub import AudioSegment

from drinkingfountain.audio import AudioConfig as MixerAudioConfig
from drinkingfountain.audio import AudioMixer, StreamingAudioPlayer, StreamingWAVWriter
from drinkingfountain.audio import TimingConfig as MixerTimingConfig
from drinkingfountain.config import Config
from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import Action, Dialogue, Script
from drinkingfountain.tts import CachedTTSBackend
from drinkingfountain.utils.narrator import transform_scene_heading
from drinkingfountain.voices import VoiceManager

logger = logging.getLogger(__name__)


@dataclass
class TimingMetrics:
    """Timing metrics for a render operation.

    Attributes:
        total_wall: Total wall clock time in seconds.
        parse_time: Time spent parsing the script in seconds.
        tts_time: Total time spent in TTS synthesis in seconds.
        tts_calls: Number of TTS synthesis calls made.
        output_time: Time spent writing to output (file/device) in seconds.
    """

    total_wall: float
    parse_time: float
    tts_time: float
    tts_calls: int
    output_time: float


@dataclass
class TimingBlock:
    """A block of content with its position in the audio timeline.

    Used for synchronized playback in the web UI.
    """

    type: str
    text: str
    character: str | None = None
    start: float = 0.0
    end: float = 0.0


class RenderResult:
    """Result of a render operation.

    Attributes:
        duration: Total duration of the audio in seconds.
        tts_calls: Number of TTS synthesis calls made.
        script_title: Title of the script.
        scene_count: Number of scenes in the script.
        character_count: Number of characters in the script.
        dialogue_count: Number of dialogue lines in the script.
        timing: TimingMetrics object with detailed timing information.
        output_path: Path to the output file if rendered to file, None if played to device.
        timing_blocks: List of TimingBlock objects for synchronized playback, or None.
    """

    def __init__(
        self,
        duration: float,
        tts_calls: int,
        script_title: str,
        scene_count: int,
        character_count: int,
        dialogue_count: int,
        timing: TimingMetrics,
        output_path: Path | None = None,
        timing_blocks: list[TimingBlock] | None = None,
    ) -> None:
        self.duration = duration
        self.tts_calls = tts_calls
        self.script_title = script_title
        self.scene_count = scene_count
        self.character_count = character_count
        self.dialogue_count = dialogue_count
        self.timing = timing
        self.output_path = output_path
        self.timing_blocks = timing_blocks


class RenderService:
    """Service for rendering a Fountain script to audio.

    This class handles the core logic of parsing a script, generating audio
    for dialogue and narration, and building the final audio mix.
    It does not handle file I/O or playback; those are CLI concerns.
    """

    def __init__(
        self,
        config: Config,
        tts: CachedTTSBackend,
        voice_mgr: VoiceManager,
        narrator_cfg,
        no_narrator: bool = False,
    ) -> None:
        """Initialize the render service.

        Args:
            config: Application configuration object.
            tts: Cached TTS backend for audio generation.
            voice_mgr: Voice manager for character voice assignment.
            narrator_cfg: Narrator configuration object.
            no_narrator: If True, narrator is disabled regardless of config.
        """
        self.config = config
        self.tts = tts
        self.voice_mgr = voice_mgr
        self.narrator_cfg = narrator_cfg
        if no_narrator:
            self.narrator_cfg.enabled = False

        # Initialize the audio mixer with config settings
        self.mixer = AudioMixer(
            config=MixerAudioConfig(
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels,
                normalize=config.audio.normalize,
                target_level=config.audio.target_level,
            ),
            timing=MixerTimingConfig(
                pause_between_lines=config.timing.pause_between_lines,
                pause_after_scene_heading=config.timing.pause_after_scene_heading,
                pause_between_scenes=config.timing.pause_between_scenes,
            ),
        )

    def render(
        self,
        script_path: Path,
        output: str | Path | None = None,
        collect_timing: bool = False,
    ) -> RenderResult:
        """Render the script to audio using streaming.

        Args:
            script_path: Path to the Fountain script file.
            output: Output file path (str or Path). If None, streams to audio device.
            collect_timing: If True, collect per-block timing data for synchronized playback.

        Returns:
            RenderResult object containing statistics and output path.

        Raises:
            FileNotFoundError: If the script file doesn't exist.
            ValueError: If the script has no dialogue.
            RuntimeError: If TTS synthesis fails for a required voice.
        """
        total_start = time.perf_counter()
        parse_start = time.perf_counter()
        logger.info("Parsing script: %s", script_path)
        parser = FountainParser()
        script_obj = parser.parse(script_path)
        parse_time = time.perf_counter() - parse_start

        return self._render_script(
            script_obj, output, collect_timing, total_start, parse_time
        )

    def render_from_string(
        self,
        script_text: str,
        output: str | Path | None = None,
        collect_timing: bool = False,
        title: str | None = None,
    ) -> RenderResult:
        """Render a Fountain script from a string.

        Args:
            script_text: Fountain-format screenplay text.
            output: Output file path (str or Path). If None, streams to audio device.
            collect_timing: If True, collect per-block timing data for synchronized playback.
            title: Optional title for the script.

        Returns:
            RenderResult object containing statistics and output path.

        Raises:
            ValueError: If the script has no dialogue.
            RuntimeError: If TTS synthesis fails for a required voice.
        """
        total_start = time.perf_counter()
        parse_start = time.perf_counter()
        logger.info("Parsing script from string")
        parser = FountainParser()
        script_obj = parser.parse_string(script_text, title=title)
        parse_time = time.perf_counter() - parse_start

        return self._render_script(
            script_obj, output, collect_timing, total_start, parse_time
        )

    def _render_script(
        self,
        script_obj: Script,
        output: str | Path | None,
        collect_timing: bool,
        total_start: float,
        parse_time: float,
    ) -> RenderResult:
        """Core render logic shared by render() and render_from_string()."""

        # Reset voice manager for this render
        self.voice_mgr.start_render()

        # Log script info
        logger.info("Script: %s", script_obj.title or "Untitled")
        logger.info("  Scenes: %d", len(script_obj.scenes))
        logger.info("  Characters: %d", len(script_obj.characters))

        dialogue_count = sum(
            1
            for scene in script_obj.scenes
            for block in scene.blocks
            if isinstance(block, Dialogue)
        )
        logger.info("  Dialogue lines: %d", dialogue_count)

        if dialogue_count == 0:
            raise ValueError("No dialogue found in script.")

        # Check for characters without voices (warn)
        characters_without_voices = []
        for char in script_obj.characters:
            if char not in self.config.voices:
                try:
                    self.voice_mgr.get_voice_for_character(char)
                except RuntimeError:
                    characters_without_voices.append(char)

        if characters_without_voices:
            logger.warning(
                "%d characters have no voice assigned and no voices are available for auto-assignment:",
                len(characters_without_voices),
            )
            for char in characters_without_voices[:5]:
                logger.warning("  - %s", char)
            if len(characters_without_voices) > 5:
                logger.warning("... and %d more", len(characters_without_voices) - 5)

        # Determine narrator voice if narrator is enabled
        narrator_voice = None
        if self.narrator_cfg.enabled:
            available_voices = self.tts.list_voices()
            if not available_voices:
                logger.warning(
                    "No voice models available for narrator. Narrator will be disabled."
                )
                self.narrator_cfg.enabled = False
            else:
                if self.narrator_cfg.voice:
                    if self.narrator_cfg.voice in available_voices:
                        narrator_voice = self.narrator_cfg.voice
                    else:
                        logger.warning(
                            "Specified narrator voice '%s' not found. Using first available voice.",
                            self.narrator_cfg.voice,
                        )
                        narrator_voice = available_voices[0]
                else:
                    narrator_voice = available_voices[0]

        # Set narrator voice in voice manager if narrator is enabled
        if self.narrator_cfg.enabled and narrator_voice is not None:
            # Check if narrator voice is the only available voice, which would leave
            # no voices for characters. In that case, disable narrator to allow characters
            # to use that voice.
            available_voices_list = self.tts.list_voices()
            remaining_voices = [v for v in available_voices_list if v != narrator_voice]
            if not remaining_voices:
                logger.warning(
                    "Narrator voice '%s' is the only available voice. Disabling narrator to ensure characters have voices.",
                    narrator_voice,
                )
                self.narrator_cfg.enabled = False
            else:
                try:
                    self.voice_mgr.set_narrator_voice(narrator_voice)
                except ValueError as e:
                    # This should not happen due to pre-check, but handle defensively
                    logger.warning(
                        "Failed to set narrator voice: %s. Disabling narrator for this render.",
                        e,
                    )
                    self.narrator_cfg.enabled = False

        # Clear any premature character voice cache that may have been populated
        # during the characters_without_voices check above. This ensures that
        # narrator voice exclusion is properly respected in auto-assignment.
        self.voice_mgr.start_render()

        # Prepare streaming output
        sample_rate = self.config.audio.sample_rate
        channels = 1 if self.config.audio.channels == "mono" else 2
        sample_width = 2  # 16-bit audio

        # Determine output format and whether we need temporary WAV conversion
        output_path = None
        use_temp_wav = False
        temp_wav_path = None
        output_format = None

        if output:
            output_path = Path(output)
            output_format = output_path.suffix.lstrip(".").lower()
            logger.info(
                "Streaming to file: %s (format: %s)", output_path, output_format
            )

            if output_format == "wav":
                writer = StreamingWAVWriter(
                    filepath=output_path,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                )
                writer.__enter__()
            else:
                # For non-WAV formats, stream to a temporary WAV file, then convert
                use_temp_wav = True
                # Create temp file in same directory (or use tempfile module)
                temp_wav_path = output_path.with_suffix(".tmp.wav")
                logger.info(
                    "Using temporary WAV file for conversion: %s", temp_wav_path
                )
                writer = StreamingWAVWriter(
                    filepath=temp_wav_path,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                )
                writer.__enter__()
        else:
            output_path = None
            logger.info("Streaming to audio device")
            writer = StreamingAudioPlayer(
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
            )

        tts_calls = 0
        tts_time = 0.0
        total_audio_duration = 0.0
        output_start = time.perf_counter()

        # Timing collection
        timing_blocks: list[TimingBlock] | None = [] if collect_timing else None
        cumulative_offset = 0.0

        try:
            # Process all scenes and blocks in order
            for scene_idx, scene in enumerate(script_obj.scenes, 1):
                logger.info("Rendering scene %d...", scene_idx)

                # Create a fresh mixer for this scene
                mixer = AudioMixer(
                    config=MixerAudioConfig(
                        sample_rate=self.config.audio.sample_rate,
                        channels=self.config.audio.channels,
                        normalize=False,  # We'll normalize at the end if needed
                        target_level=self.config.audio.target_level,
                    ),
                    timing=MixerTimingConfig(
                        pause_between_lines=self.config.timing.pause_between_lines,
                        pause_after_scene_heading=self.config.timing.pause_after_scene_heading,
                        pause_between_scenes=self.config.timing.pause_between_scenes,
                    ),
                )

                # Process scene heading
                heading = scene.heading
                if self.narrator_cfg.enabled:
                    # narrator_voice is guaranteed to be set if narrator is enabled
                    assert narrator_voice is not None, (
                        "Narrator voice should be determined before rendering"
                    )
                    try:
                        heading_text = transform_scene_heading(
                            heading.content, self.narrator_cfg.expand_int_ext
                        )
                        block_start = cumulative_offset + mixer.state.current_position
                        tts_start = time.perf_counter()
                        audio = self.tts.generate_audio(heading_text, narrator_voice)
                        tts_time += time.perf_counter() - tts_start
                        tts_calls += 1
                        # Determine pause after heading (use narrator setting or fall back to timing config)
                        pause_after_heading = (
                            self.narrator_cfg.pause_after_heading
                            if self.narrator_cfg.pause_after_heading is not None
                            else self.config.timing.pause_after_scene_heading
                        )
                        mixer.add_scene_heading(
                            heading,
                            audio,
                            pause_after=pause_after_heading,
                        )
                        if timing_blocks is not None:
                            timing_blocks.append(
                                TimingBlock(
                                    type="scene_heading",
                                    text=heading.content,
                                    start=block_start,
                                    end=cumulative_offset
                                    + mixer.state.current_position,
                                )
                            )
                    except (FileNotFoundError, RuntimeError) as e:
                        logger.warning(
                            "Narrator TTS error for scene heading: %s. Disabling narrator for the remainder of the script.",
                            e,
                        )
                        self.narrator_cfg.enabled = False
                        mixer.add_scene_heading(heading)  # Just heading, no audio
                else:
                    mixer.add_scene_heading(heading)  # Just heading, no audio

                # Process blocks within the scene
                for block in scene.blocks:
                    # Dialogue
                    if isinstance(block, Dialogue):
                        voice = self.voice_mgr.get_voice_for_character(block.character)
                        block_start = cumulative_offset + mixer.state.current_position
                        try:
                            tts_start = time.perf_counter()
                            audio = self.tts.generate_audio(block.content, voice)
                            tts_time += time.perf_counter() - tts_start
                            tts_calls += 1
                        except FileNotFoundError as e:
                            raise FileNotFoundError(
                                f"Voice model not found for voice '{voice}'. "
                                f"Use 'drinkingfountain voices download {voice}' to download it."
                            ) from e
                        except RuntimeError as e:
                            raise RuntimeError(
                                f"TTS synthesis failed for dialogue: {e}"
                            ) from e
                        mixer.add_dialogue(block, audio)
                        if timing_blocks is not None:
                            timing_blocks.append(
                                TimingBlock(
                                    type="dialogue",
                                    text=block.content,
                                    character=block.character,
                                    start=block_start,
                                    end=cumulative_offset
                                    + mixer.state.current_position,
                                )
                            )

                    # Action (stage directions) with narrator
                    elif isinstance(block, Action) and self.narrator_cfg.enabled:
                        assert narrator_voice is not None, (
                            "Narrator voice should be determined before rendering"
                        )
                        block_start = cumulative_offset + mixer.state.current_position
                        try:
                            tts_start = time.perf_counter()
                            audio = self.tts.generate_audio(
                                block.content, narrator_voice
                            )
                            tts_time += time.perf_counter() - tts_start
                            tts_calls += 1
                        except (FileNotFoundError, RuntimeError) as e:
                            logger.warning(
                                "Narrator TTS error for action block: %s. Disabling narrator for the remainder of the script.",
                                e,
                            )
                            self.narrator_cfg.enabled = False
                            continue
                        mixer.add_narrative(
                            block,
                            audio,
                            pause_before=self.narrator_cfg.pause_before_narrative,
                            pause_after=self.narrator_cfg.pause_after_narrative,
                        )
                        if timing_blocks is not None:
                            timing_blocks.append(
                                TimingBlock(
                                    type="action",
                                    text=block.content,
                                    start=block_start,
                                    end=cumulative_offset
                                    + mixer.state.current_position,
                                )
                            )
                    # Other block types are skipped

                # Get the mixed audio for this scene
                scene_audio = mixer.get_mix()
                scene_duration = len(scene_audio) / 1000.0  # pydub length in ms

                # Write scene audio to output
                writer.write_audio(scene_audio)
                total_audio_duration += scene_duration

                # Add scene transition pause (silence) after this scene if not the last
                if scene_idx < len(script_obj.scenes):
                    pause_between = self.config.timing.pause_between_scenes
                    self._add_silence(writer, pause_between)
                    total_audio_duration += pause_between
                    cumulative_offset += scene_duration + pause_between
                else:
                    cumulative_offset += scene_duration

            # Finalize writer/player
            if output:
                writer.finalize()
            else:
                writer.finalize()  # This waits for playback to complete

            # If using temporary WAV, convert to desired format
            if use_temp_wav and temp_wav_path and output_path:
                logger.info("Converting to %s...", output_format)
                try:
                    cmd = ["ffmpeg", "-i", str(temp_wav_path), "-y"]
                    if output_format == "mp3":
                        cmd.extend(["-b:a", "192k"])
                    cmd.append(str(output_path))
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, check=False
                    )
                    if result.returncode != 0:
                        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
                    logger.info("Conversion complete")
                except FileNotFoundError:
                    raise RuntimeError(
                        "ffmpeg is not installed. Please install ffmpeg to export to MP3 format.\n"
                        "See https://ffmpeg.org/download.html or use 'brew install ffmpeg' (macOS) or 'sudo apt install ffmpeg' (Ubuntu)."
                    ) from None
                finally:
                    try:
                        if temp_wav_path.exists():
                            temp_wav_path.unlink()
                            logger.debug(
                                "Removed temporary WAV file: %s", temp_wav_path
                            )
                    except OSError as e:
                        logger.warning(
                            "Failed to remove temporary file %s: %s", temp_wav_path, e
                        )

            output_time = time.perf_counter() - output_start

        except Exception:
            # Ensure writer is cleaned up on error
            if output and hasattr(writer, "_file"):
                f = writer._file
                assert f is not None, "writer._file should not be None here"
                if not f.closed:  # type: ignore
                    f.close()  # type: ignore
            # Clean up temporary WAV file if it exists
            if use_temp_wav and temp_wav_path and temp_wav_path.exists():
                try:
                    temp_wav_path.unlink()
                except OSError:
                    pass
            raise

        total_wall = time.perf_counter() - total_start

        # Build timing metrics
        timing = TimingMetrics(
            total_wall=total_wall,
            parse_time=parse_time,
            tts_time=tts_time,
            tts_calls=tts_calls,
            output_time=output_time,
        )

        return RenderResult(
            duration=total_audio_duration,
            tts_calls=tts_calls,
            script_title=script_obj.title or "Untitled",
            scene_count=len(script_obj.scenes),
            character_count=len(script_obj.characters),
            dialogue_count=dialogue_count,
            timing=timing,
            output_path=output_path,
            timing_blocks=timing_blocks,
        )

    def _add_silence(
        self, writer: StreamingWAVWriter | StreamingAudioPlayer, duration: float
    ) -> None:
        """Add silence (silent audio segment) to the stream."""

        if duration <= 0:
            return
        silence = AudioSegment.silent(
            duration=int(duration * 1000),
            frame_rate=self.config.audio.sample_rate,
        )
        if self.config.audio.channels == "mono":
            silence = silence.set_channels(1)
        else:
            silence = silence.set_channels(2)
        writer.write_audio(silence)


class VoiceService:
    """Service for managing voice models.

    This class encapsulates operations related to voice model discovery,
    downloading, and testing.
    """

    def __init__(self, max_text_length: int = 500) -> None:
        """Initialize the voice service.

        Args:
            max_text_length: Maximum text length for TTS synthesis (passed to Piper).
        """
        self.max_text_length = max_text_length

    def list_voices(self, voices_dir: Path | None = None) -> list[str]:
        """List available voice models.

        Args:
            voices_dir: Optional directory to search for voice models.

        Returns:
            List of voice IDs (strings).

        Raises:
            RuntimeError: If Piper TTS is not available.
        """
        from drinkingfountain.tts import PiperTTSBackend

        piper = PiperTTSBackend(
            voices_dir=voices_dir, max_text_length=self.max_text_length
        )
        return piper.list_voices()

    def download_voice(self, voice: str, voices_dir: Path | None = None) -> None:
        """Download a voice model.

        Args:
            voice: Voice ID to download.
            voices_dir: Optional directory to download to.

        Raises:
            RuntimeError: If download fails.
            FileNotFoundError: If voice not found in available list.
        """
        from drinkingfountain.tts import PiperTTSBackend

        piper = PiperTTSBackend(
            voices_dir=voices_dir, max_text_length=self.max_text_length
        )
        piper.download_voice(voice)

    def list_available_voices(
        self, output_format: str = "list", language: str | None = None
    ) -> list[str]:
        """List voice models available for download.

        Args:
            output_format: Ignored for now; always returns list. (Kept for CLI compatibility)
            language: Optional language code filter (e.g., 'en_US').

        Returns:
            List of voice IDs available for download.
        """
        from drinkingfountain.tts import PiperTTSBackend

        piper = PiperTTSBackend(max_text_length=self.max_text_length)
        voices = piper.list_available_voices()
        if language:
            voices = [v for v in voices if v.startswith(language + "-")]
        return voices

    def test_voice(self, voice: str, text: str, voices_dir: Path | None = None):
        """Generate sample audio with a voice.

        Args:
            voice: Voice ID to use.
            text: Text to synthesize.
            voices_dir: Optional directory containing voice models.

        Returns:
            AudioSegment with the generated audio.

        Raises:
            FileNotFoundError: If the voice is not found.
            RuntimeError: If TTS synthesis fails.
        """
        from drinkingfountain.tts import CachedTTSBackend, PiperTTSBackend

        piper = PiperTTSBackend(
            voices_dir=voices_dir, max_text_length=self.max_text_length
        )
        tts = CachedTTSBackend(piper)

        # Check if voice exists
        if voice not in tts.list_voices():
            raise FileNotFoundError(f"Voice '{voice}' not found.")

        return tts.generate_audio(text, voice)
