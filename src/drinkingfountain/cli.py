"""Command-line interface for drinkingfountain.

This module provides the main entry point for the drinkingfountain application,
including commands for rendering scripts to audio and managing voice models.
"""

import logging
import sys
import time
from pathlib import Path

import click
import yaml

from drinkingfountain.audio import AudioConfig as MixerAudioConfig
from drinkingfountain.audio import AudioMixer
from drinkingfountain.audio import TimingConfig as MixerTimingConfig
from drinkingfountain.config import Config
from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import Dialogue, Scene
from drinkingfountain.tts import CachedTTSBackend, PiperTTSBackend
from drinkingfountain.voices import VoiceManager


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity flag.

    Args:
        verbose: If True, set logging level to DEBUG, otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(None, "--version", "-v")
def cli() -> None:
    """DrinkingFountain: Convert Fountain scripts to audio plays.

    DrinkingFountain is a tool for converting Fountain-format screenplays
    into audio plays using local text-to-speech models.
    """
    pass


@cli.command()
@click.argument("script", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    required=True,
    help="Output audio file (WAV or MP3)",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Configuration file path",
)
@click.option(
    "--voices-dir",
    type=click.Path(),
    help="Directory containing voice models",
)
@click.option(
    "--cache-dir",
    type=click.Path(),
    help="TTS cache directory",
)
@click.option("--verbose", is_flag=True, help="Verbose logging")
@click.pass_context
def render(
    ctx: click.Context,
    script: str,
    output: str,
    config: str | None,
    voices_dir: str | None,
    cache_dir: str | None,
    verbose: bool,
) -> None:
    """Render a Fountain script to audio."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    # Convert string paths to Path objects
    script_path = Path(script)
    output_path = Path(output)
    config_path = Path(config) if config else None
    voices_dir_path = Path(voices_dir) if voices_dir else None
    cache_dir_path = Path(cache_dir) if cache_dir else None

    start_time = time.time()

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config_obj = Config.load(config_path)

        # Validate configuration
        validation_errors = config_obj.validate()
        if validation_errors:
            click.echo("Configuration errors:", err=True)
            for error in validation_errors:
                click.echo(f"  - {error}", err=True)
            ctx.exit(1)

        # Initialize TTS backend
        logger.info("Initializing TTS backend...")
        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
        tts = CachedTTSBackend(piper, cache_dir=cache_dir_path)

        # Check TTS availability
        if not tts.is_available():
            click.echo(
                "Error: Piper TTS is not available. Please install piper-tts:\n"
                "  pip install piper-tts\n"
                "\n"
                "And download at least one voice model:\n"
                "  drinkingfountain voices download <voice_id>",
                err=True,
            )
            ctx.exit(1)

        # Initialize voice manager
        voice_mgr = VoiceManager(tts)

        # Apply voice overrides from config
        if config_obj.voices:
            logger.info(
                "Applying %d voice overrides from config...", len(config_obj.voices)
            )
            for character, voice in config_obj.voices.items():
                if voice not in tts.list_voices():
                    click.echo(
                        f"Warning: Voice '{voice}' for character '{character}' not found in available voices.",
                        err=True,
                    )
                voice_mgr.set_character_voice(character, voice)

        # Parse script
        logger.info("Parsing script: %s", script_path)
        parser = FountainParser()
        script_obj = parser.parse(script_path)

        click.echo(f"Script: {script_obj.title or 'Untitled'}")
        click.echo(f"  Scenes: {len(script_obj.scenes)}")
        click.echo(f"  Characters: {len(script_obj.characters)}")

        # Find all dialogue blocks
        dialogue_blocks: list[tuple[Scene, Dialogue]] = []
        for scene in script_obj.scenes:
            for block in scene.blocks:
                if isinstance(block, Dialogue):
                    dialogue_blocks.append((scene, block))

        click.echo(f"  Dialogue lines: {len(dialogue_blocks)}")

        if not dialogue_blocks:
            click.echo("Warning: No dialogue found in script.", err=True)
            ctx.exit(1)

        # Check for characters without voices (warn)
        characters_without_voices = []
        for char in script_obj.characters:
            if char not in config_obj.voices:
                # Try to get a voice (this will auto-assign if possible)
                try:
                    voice_mgr.get_voice_for_character(char)
                except RuntimeError:
                    characters_without_voices.append(char)

        if characters_without_voices:
            click.echo(
                f"Warning: {len(characters_without_voices)} characters have no voice assigned "
                f"and no voices are available for auto-assignment:",
                err=True,
            )
            for char in characters_without_voices[:5]:  # Show up to 5
                click.echo(f"  - {char}", err=True)
            if len(characters_without_voices) > 5:
                click.echo(
                    f"  ... and {len(characters_without_voices) - 5} more", err=True
                )

        # Initialize mixer
        mixer = AudioMixer(
            config=MixerAudioConfig(
                sample_rate=config_obj.audio.sample_rate,
                channels=config_obj.audio.channels,
                normalize=config_obj.audio.normalize,
                target_level=config_obj.audio.target_level,
            ),
            timing=MixerTimingConfig(
                pause_between_lines=config_obj.timing.pause_between_lines,
                pause_after_scene_heading=config_obj.timing.pause_after_scene_heading,
                pause_between_scenes=config_obj.timing.pause_between_scenes,
            ),
        )

        # Track statistics
        tts_calls = 0

        # Generate audio for each dialogue block
        click.echo("\nGenerating audio...")
        current_scene = None

        for scene, dialogue in dialogue_blocks:
            # Add scene heading if entering a new scene
            if scene != current_scene:
                mixer.add_scene_heading(scene.heading)
                current_scene = scene

            # Get voice for character
            voice = voice_mgr.get_voice_for_character(dialogue.character)

            # Generate audio
            try:
                audio = tts.generate_audio(dialogue.content, voice)
                tts_calls += 1
            except FileNotFoundError:
                click.echo(
                    f"\nError: Voice model not found for voice '{voice}'. "
                    f"Use 'drinkingfountain voices download {voice}' to download it.",
                    err=True,
                )
                ctx.exit(1)
            except RuntimeError as e:
                click.echo(f"\nError: TTS synthesis failed: {e}", err=True)
                ctx.exit(1)

            # Add to mixer
            mixer.add_dialogue(dialogue, audio)

        # Export
        logger.info("Exporting to %s...", output_path)
        output_format = output_path.suffix.lstrip(".").lower()
        if output_format not in ("wav", "mp3"):
            click.echo(
                f"Error: Unsupported output format '{output_format}'. Use WAV or MP3.",
                err=True,
            )
            ctx.exit(1)

        # For MP3, use a reasonable bitrate
        parameters = ["-q:a", "0"] if output_format == "mp3" else None

        mixer.export(output_path, format=output_format, parameters=parameters)

        # Print statistics
        elapsed = time.time() - start_time
        duration = mixer.duration()

        click.echo("\n✓ Render complete!")
        click.echo(f"  Output: {output_path}")
        click.echo(f"  Duration: {duration:.2f} seconds ({duration / 60:.2f} minutes)")
        click.echo(f"  Processing time: {elapsed:.2f} seconds")
        click.echo(f"  TTS calls: {tts_calls}")
        # TODO: Add cache hit tracking if we expose it from CachedTTSBackend

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)
    except yaml.YAMLError as e:
        click.echo(f"Error: Configuration file is invalid YAML: {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        ctx.exit(1)


# Voices command group
@cli.group("voices")
def voices() -> None:
    """Manage voice models."""
    pass


@voices.command("list")
@click.option(
    "--voices-dir",
    type=click.Path(),
    help="Directory containing voice models",
)
def voices_list(voices_dir: str | None) -> None:
    """List available voice models."""
    try:
        voices_dir_path = Path(voices_dir) if voices_dir else None
        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
        voices = piper.list_voices()

        if not voices:
            click.echo("No voice models found.")
            click.echo(f"Search directory: {piper.voices_dir}")
            click.echo(
                "\nDownload a voice with: drinkingfountain voices download <voice_id>"
            )
            return

        click.echo(f"Available voices ({len(voices)}):")
        for voice in sorted(voices):
            click.echo(f"  {voice}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@voices.command("download")
@click.argument("voice", type=str)
@click.option(
    "--voices-dir",
    type=click.Path(),
    help="Directory to download to",
)
def voices_download(voice: str, voices_dir: str | None) -> None:
    """Download a voice model."""
    try:
        voices_dir_path = Path(voices_dir) if voices_dir else None
        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
        click.echo(f"Downloading voice '{voice}'...")
        piper.download_voice(voice)
        click.echo(f"✓ Voice '{voice}' downloaded to {piper.voices_dir}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@voices.command("test")
@click.argument("voice", type=str)
@click.argument("text", type=str)
@click.option(
    "--voices-dir",
    type=click.Path(),
    help="Directory containing voice models",
)
@click.option(
    "--output",
    type=click.Path(),
    help="Save to file instead of playing",
)
def voices_test(
    voice: str, text: str, voices_dir: str | None, output: str | None
) -> None:
    """Generate sample audio with a voice."""
    try:
        voices_dir_path = Path(voices_dir) if voices_dir else None
        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
        tts = CachedTTSBackend(piper)

        # Check if voice exists
        if voice not in tts.list_voices():
            click.echo(f"Error: Voice '{voice}' not found.", err=True)
            click.echo("Use 'drinkingfountain voices list' to see available voices.")
            sys.exit(1)

        click.echo(f"Generating audio with voice '{voice}'...")
        click.echo(f"Text: {text}")

        audio = tts.generate_audio(text, voice)

        if output:
            # Save to file
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            audio.export(output_path, format=output_path.suffix.lstrip(".").lower())
            click.echo(
                f"✓ Audio saved to {output_path} (duration: {len(audio) / 1000:.2f}s)"
            )
        else:
            # Try to play audio
            try:
                import simpleaudio as sa  # type: ignore

                click.echo("Playing audio... (press Ctrl+C to stop)")
                # Convert to raw audio data
                raw_data = audio.raw_data
                play_obj = sa.play_buffer(
                    raw_data,
                    num_channels=audio.channels,
                    bytes_per_sample=audio.sample_width,
                    sample_rate=audio.frame_rate,
                )
                play_obj.wait_done()
            except ImportError:
                click.echo(
                    "Note: Audio playback requires 'simpleaudio'. Install with: pip install simpleaudio\n"
                    "Saving to temporary file instead...",
                    err=True,
                )
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    audio.export(tmp.name, format="wav")
                    click.echo(f"Audio saved to: {tmp.name}")
                    click.echo(
                        "Play with: afplay {tmp.name} (macOS) or play {tmp.name} (Linux)"
                    )
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
