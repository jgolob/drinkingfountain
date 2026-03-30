"""Command-line interface for drinkingfountain.

This module provides the main entry point for the drinkingfountain application,
including commands for rendering scripts to audio and managing voice models.
"""

import logging
import sys
from pathlib import Path

import click
import yaml

from drinkingfountain.config import Config
from drinkingfountain.services import RenderService, VoiceService
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


def _play_mix(audio) -> None:
    """Play an audio segment through the default audio device.

    Args:
        audio: AudioSegment to play.

    Raises:
        SystemExit: If simpleaudio is not available or playback fails.
    """
    try:
        import simpleaudio as sa

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
            "Error: Audio playback requires 'simpleaudio'. Install with:\n"
            "  pip install simpleaudio\n"
            "\n"
            "Alternatively, use --output to save to a file instead of playing.",
            err=True,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nPlayback interrupted by user.")
        # simpleaudio doesn't require explicit stop when using wait_done,
        # but we exit cleanly
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error during playback: {e}", err=True)
        sys.exit(1)


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
    required=False,
    help="Output audio file (WAV or MP3). If not provided, audio will play through the default audio device.",
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
@click.option(
    "--no-narrator",
    is_flag=True,
    help="Disable narrator for stage directions and scene headings",
)
@click.pass_context
def render(
    ctx: click.Context,
    script: str,
    output: str,
    config: str | None,
    voices_dir: str | None,
    cache_dir: str | None,
    verbose: bool,
    no_narrator: bool,
) -> None:
    """Render a Fountain script to audio."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    script_path = Path(script)
    config_path = Path(config) if config else None
    voices_dir_path = Path(voices_dir) if voices_dir else None
    cache_dir_path = Path(cache_dir) if cache_dir else None

    try:
        # Load and validate configuration
        logger.info("Loading configuration...")
        config_obj = Config.load(config_path)
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

        # Initialize voice manager and apply overrides
        voice_mgr = VoiceManager(tts)
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

        # Create render service and render
        click.echo("\nGenerating audio...")
        service = RenderService(
            config=config_obj,
            tts=tts,
            voice_mgr=voice_mgr,
            narrator_cfg=config_obj.narrator,
            no_narrator=no_narrator,
        )
        result = service.render(script_path, output=output)

        # Output user-facing info
        click.echo(f"Script: {result.script_title}")
        click.echo(f"  Scenes: {result.scene_count}")
        click.echo(f"  Characters: {result.character_count}")
        click.echo(f"  Dialogue lines: {result.dialogue_count}")

        if result.output_path:
            # File output
            click.echo("\n✓ Render complete!")
            click.echo(f"  Output: {result.output_path}")
        else:
            # Device playback
            click.echo("\n✓ Playback complete!")

        # Display timing information
        click.echo(
            f"  Duration: {result.duration:.2f} seconds ({result.duration / 60:.2f} minutes)"
        )
        click.echo(f"  Time taken: {result.timing.total_wall:.2f} seconds")
        click.echo(
            f"  TTS: {result.timing.tts_time:.2f} seconds "
            f"({result.timing.tts_calls} calls, avg {result.timing.tts_time / result.timing.tts_calls:.2f} s/call)"
        )
        click.echo(f"  Output: {result.timing.output_time:.2f} seconds")
        click.echo(f"  Parse: {result.timing.parse_time:.2f} seconds")

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
        service = VoiceService()
        voices_dir_path = Path(voices_dir) if voices_dir else None
        voices = service.list_voices(voices_dir_path)

        if not voices:
            # Show search directory by instantiating PiperTTSBackend
            from drinkingfountain.tts import PiperTTSBackend

            piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
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
        service = VoiceService()
        voices_dir_path = Path(voices_dir) if voices_dir else None
        click.echo(f"Downloading voice '{voice}'...")
        service.download_voice(voice, voices_dir_path)
        # Show download directory
        from drinkingfountain.tts import PiperTTSBackend

        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)
        click.echo(f"✓ Voice '{voice}' downloaded to {piper.voices_dir}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@voices.command("available")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["list", "json"], case_sensitive=False),
    default="list",
    help="Output format (list or json)",
)
@click.option(
    "--language",
    type=str,
    help="Filter by language code (e.g., en_US, fr_FR)",
)
def voices_available(output_format: str, language: str | None) -> None:
    """List voice models available for download from Piper."""
    try:
        service = VoiceService()
        voices = service.list_available_voices(language=language)

        if not voices:
            click.echo("No voices match the criteria.")
            return

        if output_format == "list":
            click.echo(f"Available voices for download ({len(voices)}):")
            for voice in sorted(voices):
                click.echo(f"  {voice}")
        else:  # json format
            import json

            click.echo(json.dumps(sorted(voices), indent=2))
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
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
        service = VoiceService()
        voices_dir_path = Path(voices_dir) if voices_dir else None
        click.echo(f"Generating audio with voice '{voice}'...")
        click.echo(f"Text: {text}")
        audio = service.test_voice(voice, text, voices_dir_path)

        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            audio.export(output_path, format=output_path.suffix.lstrip(".").lower())
            click.echo(
                f"✓ Audio saved to {output_path} (duration: {len(audio) / 1000:.2f}s)"
            )
        else:
            # Try to play audio
            try:
                import simpleaudio as sa

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
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
