"""Business logic services for drinkingfountain.

This module contains service classes that encapsulate core functionality
for rendering scripts and managing voices, separating them from CLI concerns.
"""

import logging
import time
from pathlib import Path

from drinkingfountain.audio import AudioConfig as MixerAudioConfig
from drinkingfountain.audio import AudioMixer
from drinkingfountain.audio import TimingConfig as MixerTimingConfig
from drinkingfountain.config import Config
from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import Action, Dialogue
from drinkingfountain.tts import CachedTTSBackend
from drinkingfountain.utils.narrator import transform_scene_heading
from drinkingfountain.voices import VoiceManager

logger = logging.getLogger(__name__)


class RenderResult:
    """Result of a render operation.

    Attributes:
        mixer: The AudioMixer containing the final audio mix.
        duration: Total duration of the audio in seconds.
        tts_calls: Number of TTS synthesis calls made.
        elapsed: Total elapsed time in seconds.
        script_title: Title of the script.
        scene_count: Number of scenes in the script.
        character_count: Number of characters in the script.
        dialogue_count: Number of dialogue lines in the script.
    """

    def __init__(
        self,
        mixer: AudioMixer,
        duration: float,
        tts_calls: int,
        elapsed: float,
        script_title: str,
        scene_count: int,
        character_count: int,
        dialogue_count: int,
    ) -> None:
        self.mixer = mixer
        self.duration = duration
        self.tts_calls = tts_calls
        self.elapsed = elapsed
        self.script_title = script_title
        self.scene_count = scene_count
        self.character_count = character_count
        self.dialogue_count = dialogue_count


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

    def render(self, script_path: Path) -> RenderResult:
        """Render the script to an audio mix.

        Args:
            script_path: Path to the Fountain script file.

        Returns:
            RenderResult object containing the mixer and statistics.

        Raises:
            FileNotFoundError: If the script file doesn't exist.
            ValueError: If the script has no dialogue.
            RuntimeError: If TTS synthesis fails for a required voice.
        """
        start_time = time.time()

        # Parse script
        logger.info("Parsing script: %s", script_path)
        parser = FountainParser()
        script_obj = parser.parse(script_path)

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
                logger.warning("  ... and %d more", len(characters_without_voices) - 5)

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

        tts_calls = 0

        # Process all scenes and blocks in order
        for scene in script_obj.scenes:
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
                    audio = self.tts.generate_audio(heading_text, narrator_voice)
                    tts_calls += 1
                    self.mixer.add_scene_heading(
                        heading,
                        audio,
                        pause_after=self.narrator_cfg.pause_after_heading,
                    )
                except (FileNotFoundError, RuntimeError) as e:
                    logger.warning(
                        "Narrator TTS error for scene heading: %s. Disabling narrator for the remainder of the script.",
                        e,
                    )
                    self.narrator_cfg.enabled = False
                    self.mixer.add_scene_heading(heading)
            else:
                self.mixer.add_scene_heading(heading)

            # Process blocks within the scene
            for block in scene.blocks:
                # Dialogue
                if isinstance(block, Dialogue):
                    voice = self.voice_mgr.get_voice_for_character(block.character)
                    try:
                        audio = self.tts.generate_audio(block.content, voice)
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
                    self.mixer.add_dialogue(block, audio)

                # Action (stage directions) with narrator
                elif isinstance(block, Action) and self.narrator_cfg.enabled:
                    # narrator_voice is guaranteed to be set if narrator is enabled
                    assert narrator_voice is not None, (
                        "Narrator voice should be determined before rendering"
                    )
                    try:
                        audio = self.tts.generate_audio(block.content, narrator_voice)
                        tts_calls += 1
                    except (FileNotFoundError, RuntimeError) as e:
                        logger.warning(
                            "Narrator TTS error for action block: %s. Disabling narrator for the remainder of the script.",
                            e,
                        )
                        self.narrator_cfg.enabled = False
                        continue
                    self.mixer.add_narrative(
                        block,
                        audio,
                        pause_before=self.narrator_cfg.pause_before_narrative,
                        pause_after=self.narrator_cfg.pause_after_narrative,
                    )
                # Other block types (Parenthetical, Transition, etc.) are skipped

        elapsed = time.time() - start_time
        duration = self.mixer.duration()

        return RenderResult(
            mixer=self.mixer,
            duration=duration,
            tts_calls=tts_calls,
            elapsed=elapsed,
            script_title=script_obj.title or "Untitled",
            scene_count=len(script_obj.scenes),
            character_count=len(script_obj.characters),
            dialogue_count=dialogue_count,
        )


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
