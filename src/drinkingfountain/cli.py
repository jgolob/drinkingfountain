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
from drinkingfountain.tts.factory import (
    create_bulk_voice_catalog_backend,
    create_cached_tts_backend,
    create_tts_backend,
)
from drinkingfountain.voices import VoiceManager


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
        tts = create_cached_tts_backend(
            config_obj.backend,
            voices_dir=voices_dir_path,
            cache_dir=cache_dir_path,
            max_text_length=500,
        )

        if not tts.is_available():
            backend_label = (
                "Piper TTS"
                if config_obj.backend == "piper"
                else f"TTS backend '{config_obj.backend}'"
            )
            click.echo(
                f"Error: {backend_label} is not available.\n"
                "\n"
                "Install the backend dependencies and download at least one voice model:\n"
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
            backend = create_tts_backend(
                voices_dir=voices_dir_path, max_text_length=500
            )
            search_dir = getattr(backend, "voices_dir", None)
            click.echo("No voice models found.")
            if search_dir is not None:
                click.echo(f"Search directory: {search_dir}")
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
        backend = create_tts_backend(voices_dir=voices_dir_path, max_text_length=500)
        download_dir = getattr(backend, "voices_dir", "the configured voice store")
        click.echo(f"✓ Voice '{voice}' downloaded to {download_dir}")
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


@voices.command("download-bulk")
@click.option(
    "--language",
    "-l",
    type=str,
    help="Language code (e.g., 'en_US', 'fr_FR'). Required unless configured in config file.",
)
@click.option(
    "--quality",
    "-q",
    type=click.Choice(
        ["x-low", "low", "medium", "high", "x-high"], case_sensitive=False
    ),
    help="Quality level for voice models.",
)
@click.option(
    "--max-workers",
    "-w",
    type=int,
    help="Maximum number of concurrent downloads (default: 3 or from config).",
)
@click.option(
    "--stop-on-error",
    is_flag=True,
    help="Stop all downloads on the first error. Default: continue on errors.",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Configuration file path",
)
@click.pass_context
def voices_download_bulk(
    ctx: click.Context,
    language: str | None,
    quality: str | None,
    max_workers: int | None,
    stop_on_error: bool,
    config: str | None,
) -> None:
    """Download all voice models for a specific language in bulk.

    This command downloads all available voice models for a given language
    (and optional quality) from the Piper TTS voice catalog. Downloads are
    performed in parallel for speed.

    The language can be specified via --language option or configured in the
    config file under voice_management.bulk_download_language. If neither is
    provided, the command will fail.

    Examples:

        drinkingfountain voices download-bulk --language en_US

        drinkingfountain voices download-bulk --language en_US --quality medium

        drinkingfountain voices download-bulk --language fr_FR --max-workers 5 --stop-on-error
    """
    setup_logging(False)  # Use default logging level (INFO)
    logger = logging.getLogger(__name__)

    config_path = Path(config) if config else None

    try:
        # Load configuration
        logger.info("Loading configuration...")
        config_obj = Config.load(config_path)

        # Determine language: CLI option takes precedence over config
        bulk_lang = language or config_obj.voice_management.bulk_download_language
        if not bulk_lang:
            click.echo(
                "Error: Language must be specified via --language option or configured in "
                "config file under 'voice_management.bulk_download_language'.",
                err=True,
            )
            ctx.exit(1)

        # Determine max_workers: CLI option overrides config, default to 3
        max_workers_val = (
            max_workers or config_obj.voice_management.max_concurrent_downloads
        )
        if max_workers_val < 1:
            click.echo(
                f"Error: max_workers must be at least 1, got {max_workers_val}.",
                err=True,
            )
            ctx.exit(1)

        # Determine quality (can be from config if not provided via CLI)
        # Config has bulk_download_quality, use it if CLI didn't specify
        quality_val = quality or config_obj.voice_management.bulk_download_quality
        if quality_val:
            quality_val = quality_val.lower()

        # Initialize TTS backend
        logger.info("Initializing TTS backend...")
        backend = create_bulk_voice_catalog_backend(
            config_obj.backend, max_text_length=500
        )

        if not backend.is_available():
            click.echo(
                f"Error: TTS backend '{config_obj.backend}' is not available.\n",
                err=True,
            )
            ctx.exit(1)

        # Progress callback to display download progress
        completed_count = 0

        def progress_callback(completed: int, total: int) -> None:
            nonlocal completed_count
            completed_count = completed
            click.echo(f"Progress: {completed}/{total} voices downloaded...")

        # Perform bulk download
        click.echo(
            f"Starting bulk download for language '{bulk_lang}'"
            f"{f' (quality: {quality_val})' if quality_val else ''}..."
        )
        click.echo(f"Max concurrent workers: {max_workers_val}")
        click.echo(f"Stop on error: {stop_on_error}")

        success_count, failure_count = backend.download_voices_by_language(
            language=bulk_lang,
            quality=quality_val,
            max_workers=max_workers_val,
            progress_callback=progress_callback,
            stop_on_error=stop_on_error,
        )

        # Print summary
        click.echo()
        click.echo("Bulk download complete!")
        click.echo(f"  Successfully downloaded: {success_count} voices")
        click.echo(f"  Failed: {failure_count} voices")

        if failure_count > 0:
            logger.warning("Some voice downloads failed. Check logs above for details.")

    except KeyboardInterrupt:
        click.echo("\nDownload interrupted by user.", err=True)
        ctx.exit(130)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)
    except yaml.YAMLError as e:
        click.echo(f"Error: Configuration file is invalid YAML: {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        logger.exception("Unexpected error in voices_download_bulk")
        ctx.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
