# Voice Management Enhancement Design

## Overview

This document details the design for three enhancements to voice handling in the Drinking Fountain project:

1. **Bulk voice download** - Download all Piper voices for a specified language and quality level
2. **Consistent voice-to-character mapping** - Ensure the same character always gets the same voice throughout a script render
3. **Narrator voice isolation** - Automatically exclude the narrator's voice from auto-assignment pool

These enhancements improve usability, consistency, and prevent accidental voice conflicts.

---

## 1. Architectural Overview

### Current Architecture

```
┌─────────────────┐
│   CLI (render)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         RenderService                   │
│  - Parses script                       │
│  - Determines narrator voice           │
│  - Iterates scenes/blocks              │
│  - Calls voice_mgr.get_voice_for_      │   character for each dialogue block
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         VoiceManager                    │
│  - overrides: dict[char->voice]        │
│  - default_voice: str | None           │
│  - auto_pool: list[str] (cached)       │
│  - get_voice_for_character(char) -> str│
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         TTS Backend (PiperTTSBackend)  │
│  - list_voices()                       │
│  - generate_audio(text, voice)         │
└─────────────────────────────────────────┘
```

**Problems with current design:**
- `VoiceManager.get_voice_for_character()` uses `random.choice(auto_pool)` for auto-assignment, causing inconsistent voice assignment for the same character across a script
- No per-character caching - each call is independent
- Narrator voice is not excluded from auto-assignment pool, potentially assigning narrator voice to a character
- No bulk download capability - users must download voices one-by-one

### Enhanced Architecture

```
┌─────────────────┐
│   CLI (render)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         RenderService                   │
│  - Creates fresh VoiceManager per render│
│  - Calls voice_mgr.start_render()       │◄─ RESET character voice cache
│  - For each dialogue:                  │
│      voice = voice_mgr.get_voice_for_   │
│               character(char)           │
│      (now consistent per character)    │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         VoiceManager                    │
│  - overrides: dict[char->voice]        │
│  - default_voice: str | None           │
│  - auto_pool: list[str] (cached)       │
│  - char_voice_cache: dict[char->voice] │◄─ NEW: per-character cache
│  - narrator_voice: str | None          │◄─ NEW: narrator voice to exclude
│  - start_render() -> reset cache       │
│  - get_voice_for_character(char) -> str│   (now caches per char)
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         TTS Backend (PiperTTSBackend)  │
│  - list_voices()                       │
│  - list_available_voices()             │
│  - download_voice(voice)               │
│  - download_voices_bulk(voices)        │◄─ NEW: bulk download
└─────────────────────────────────────────┘
```

**Key changes:**
- `VoiceManager` now tracks per-character voice assignments during a render via `char_voice_cache`
- `VoiceManager` stores `narrator_voice` and excludes it from auto-assignment pool
- `VoiceManager.start_render()` resets the character cache at the beginning of each render
- `PiperTTSBackend.download_voices_bulk()` downloads multiple voices with progress and error handling
- CLI gains new `drinkingfountain voices download-bulk` command

---

## 2. Detailed Class Changes

### 2.1 VoiceManager (src/drinkingfountain/voices/manager.py)

#### Current Implementation

```python
class VoiceManager:
    def __init__(self, backend: TTSBackend) -> None:
        self.backend = backend
        self._overrides: MutableMapping[str, str] = {}
        self._default_voice: str | None = None
        self._auto_pool: list[str] = []

    def get_voice_for_character(self, character: str) -> str:
        if character in self._overrides:
            return self._overrides[character]
        if self._default_voice:
            return self._default_voice
        if not self._auto_pool:
            voices = self.backend.list_voices()
            if not voices:
                raise RuntimeError("No voices available...")
            self._auto_pool = voices.copy()
        return random.choice(self._auto_pool)  # ◄─ RANDOM: inconsistent!
```

#### Enhanced Implementation

```python
class VoiceManager:
    """Manages voice assignment for characters and voice model downloads.

    The VoiceManager sits between the script and the TTS backend. It:
    - Tracks which voice to use for each character (with per-render caching)
    - Allows manual overrides (character -> voice)
    - Provides a default voice for unspecified characters
    - Auto-assigns voices from the available pool if no default set
    - Excludes narrator voice from auto-assignment pool (if set)
    - Delegates voice listing and downloading to the backend
    """

    def __init__(self, backend: TTSBackend) -> None:
        """Initialize with a TTS backend.

        Args:
            backend: The TTS backend to use for synthesis and voice queries.
        """
        self.backend = backend
        self._overrides: MutableMapping[str, str] = {}
        self._default_voice: str | None = None
        self._auto_pool: list[str] = []
        self._char_voice_cache: dict[str, str] = {}  # NEW: per-character cache
        self._narrator_voice: str | None = None      # NEW: narrator voice to exclude

    def set_narrator_voice(self, voice: str | None) -> None:
        """Set the narrator voice to exclude from auto-assignment pool.

        This should be called by RenderService before rendering begins
        if narrator is enabled. Pass None to clear.

        Args:
            voice: Voice identifier, or None to clear.
        """
        self._narrator_voice = voice
        # Clear auto pool cache so exclusion takes effect
        self._auto_pool = []

    def start_render(self) -> None:
        """Reset character voice cache at the start of a new render.

        This ensures consistent voice assignment throughout a single render
        while allowing different renders to use different assignments.
        """
        self._char_voice_cache.clear()
        # Also clear auto pool to refresh if voices changed
        self._auto_pool = []

    def get_voice_for_character(self, character: str) -> str:
        """Get the voice ID to use for a given character.

        Resolution order:
        1. Explicit override for the character.
        2. Default voice if set.
        3. Random selection from available pool (excluding narrator).

        The result is cached for the duration of a render (until start_render()
        is called) to ensure consistency.

        Args:
            character: Character name.

        Returns:
            A voice identifier string.

        Raises:
            RuntimeError: If no voices are available from the backend.
            ValueError: If auto-assignment pool becomes empty after narrator exclusion.
        """
        # Check cache first (for consistency within a render)
        if character in self._char_voice_cache:
            return self._char_voice_cache[character]

        # Determine voice (same logic as before, but with narrator exclusion)
        if character in self._overrides:
            voice = self._overrides[character]
        elif self._default_voice:
            voice = self._default_voice
        else:
            # Auto-assign: build pool excluding narrator
            if not self._auto_pool:
                voices = self.backend.list_voices()
                if not voices:
                    raise RuntimeError(
                        "No voices available. Please download at least one voice model."
                    )
                # Exclude narrator voice from auto-assignment pool
                if self._narrator_voice:
                    original_count = len(voices)
                    voices = [v for v in voices if v != self._narrator_voice]
                    if original_count > 0 and len(voices) < original_count:
                        logger.debug(
                            "Excluded narrator voice '%s' from auto-assignment pool. "
                            "Pool size: %d -> %d",
                            self._narrator_voice,
                            original_count,
                            len(voices),
                        )
                    # Edge case: pool becomes empty after exclusion
                    if not voices:
                        raise ValueError(
                            "No voices available for character assignment. "
                            f"The narrator voice '{self._narrator_voice}' has been excluded, "
                            "leaving no voices for characters. Either add more voices or "
                            "assign specific voices to characters via configuration."
                        )
                self._auto_pool = voices.copy()
            voice = random.choice(self._auto_pool)

        # Cache for future calls in the same render
        self._char_voice_cache[character] = voice
        return voice

    def clear_overrides(self) -> None:
        """Remove all character-specific voice overrides."""
        self._overrides.clear()

    def get_overrides(self) -> dict[str, str]:
        """Get a copy of the current character voice overrides.

        The returned dictionary is a mutable copy; modifications do not affect
        the manager's internal state.
        """
        return dict(self._overrides)

    def download_voice(self, voice: str) -> None:
        """Download a voice model via the backend.

        Args:
            voice: Voice identifier to download.

        Raises:
            ValueError: If the voice identifier is invalid.
            RuntimeError: If download fails.
        """
        self.backend.download_voice(voice)
        # Clear caches so new voice is included
        self._auto_pool = []
        self._char_voice_cache.clear()  # Could also clear, though not strictly needed

    def list_available_voices(self) -> list[str]:
        """Return the list of voices available from the backend."""
        return self.backend.list_voices()
```

**Key changes:**
- Added `_char_voice_cache: dict[str, str]` to cache voice assignments per character
- Added `_narrator_voice: str | None` to track narrator voice for exclusion
- Added `start_render()` method to reset cache at render start
- Modified `get_voice_for_character()` to:
  - Check cache first
  - Build auto pool excluding narrator voice
  - Cache result before returning
- `download_voice()` now also clears `_char_voice_cache` for safety

### 2.2 PiperTTSBackend (src/drinkingfountain/tts/piper.py)

#### New Method: `download_voices_bulk`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import logging

logger = logging.getLogger(__name__)

class PiperTTSBackend(TTSBackend):
    # ... existing code ...

    def download_voices_bulk(
        self,
        voices: list[str],
        *,
        max_workers: int = 4,
        progress_callback: Callable[[int, int, str], None] | None = None,
        stop_on_error: bool = False,
    ) -> tuple[int, int]:
        """Download multiple voice models in parallel.

        Args:
            voices: List of voice identifiers to download.
            max_workers: Maximum number of parallel downloads (default: 4).
            progress_callback: Optional callback(completed, total, current_voice) for progress.
            stop_on_error: If True, stop all downloads on first error. If False, continue
                         and return summary of successes/failures.

        Returns:
            Tuple of (successful_count, failed_count).

        Raises:
            RuntimeError: If stop_on_error=True and any download fails.
        """
        if not voices:
            return (0, 0)

        total = len(voices)
        completed = 0
        failed = 0
        errors: list[tuple[str, str]] = []

        # Use ThreadPoolExecutor for parallel downloads
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all download tasks
            future_to_voice = {
                executor.submit(self._download_single_voice, voice): voice
                for voice in voices
            }

            # Process as they complete
            for future in as_completed(future_to_voice):
                voice = future_to_voice[future]
                try:
                    future.result()  # This will raise if download failed
                    completed += 1
                    logger.info("Successfully downloaded voice '%s'", voice)
                except Exception as e:
                    failed += 1
                    errors.append((voice, str(e)))
                    logger.error("Failed to download voice '%s': %s", voice, e)
                    if stop_on_error:
                        # Cancel remaining futures
                        for f in future_to_voice:
                            f.cancel()
                        raise RuntimeError(
                            f"Bulk download stopped due to error: {e}"
                        ) from e

                # Call progress callback if provided
                if progress_callback:
                    try:
                        progress_callback(completed + failed, total, voice)
                    except Exception as e:
                        logger.warning("Progress callback raised: %s", e)

        # Log summary
        if failed > 0:
            logger.warning(
                "Bulk download completed: %d succeeded, %d failed",
                completed,
                failed,
            )
            for voice, error in errors[:10]:  # Log first 10 errors
                logger.warning("  - %s: %s", voice, error)
            if len(errors) > 10:
                logger.warning("  ... and %d more errors", len(errors) - 10)
        else:
            logger.info("Bulk download completed successfully: %d/%d", completed, total)

        return (completed, failed)

    def _download_single_voice(self, voice: str) -> None:
        """Download a single voice model. Internal method for bulk operations.

        This is similar to download_voice() but without the success message
        and cache clearing (those are handled by bulk method).

        Args:
            voice: The voice identifier to download.

        Raises:
            RuntimeError: If the download fails.
        """
        if not PIPER_AVAILABLE:
            raise RuntimeError("Piper TTS is not installed. Cannot download voices.")

        download_dir = self.voices_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "piper.download_voices",
                    voice,
                    "--download-dir",
                    str(download_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            if "HTTP Error 404" in error_msg or "Not Found" in error_msg:
                raise RuntimeError(
                    f"Voice '{voice}' not found. The voice name may be incorrect or not available."
                ) from e
            raise RuntimeError(f"Voice download failed: {error_msg}") from e
        except Exception as e:
            raise RuntimeError(f"Voice download failed: {e}") from e
```

**Key changes:**
- Added `download_voices_bulk()` method for parallel downloads
- Supports progress callbacks and error handling strategies
- Uses `ThreadPoolExecutor` for concurrency
- Returns success/failure counts
- `_download_single_voice()` helper for thread pool workers

### 2.3 RenderService (src/drinkingfountain/services.py)

#### Changes in `render()` method

```python
class RenderService:
    def render(
        self, script_path: Path, output: str | Path | None = None
    ) -> RenderResult:
        """Render the script to audio using streaming."""
        total_start = time.perf_counter()

        # Parse script (unchanged)
        parse_start = time.perf_counter()
        parser = FountainParser()
        script_obj = parser.parse(script_path)
        parse_time = time.perf_counter() - parse_start

        # ... logging ...

        # NEW: Reset voice manager cache at start of render
        self.voice_mgr.start_render()

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

            # NEW: Set narrator voice in VoiceManager for exclusion
            self.voice_mgr.set_narrator_voice(narrator_voice)

        # ... rest of render logic (unchanged, but get_voice_for_character now caches) ...
```

**Key changes:**
- Call `self.voice_mgr.start_render()` at the beginning to reset character cache
- After determining narrator voice, call `self.voice_mgr.set_narrator_voice(narrator_voice)` to set exclusion
- No other changes needed - `get_voice_for_character()` will now use caching and exclusion automatically

### 2.4 Config (src/drinkingfountain/config/settings.py)

#### New Configuration Options

Add to `NarratorConfig` (or create separate `VoiceManagementConfig`):

```python
@dataclass
class VoiceManagementConfig:
    """Configuration for voice management features.

    Attributes:
        bulk_download_language: Default language code for bulk downloads (e.g., "en_US").
        bulk_download_quality: Default quality level for bulk downloads ("x-low", "low",
                              "medium", "high", "x-high").
        max_concurrent_downloads: Maximum parallel downloads for bulk operations (default: 4).
    """
    bulk_download_language: str | None = None
    bulk_download_quality: str | None = None
    max_concurrent_downloads: int = 4

@dataclass
class Config:
    # Existing fields...
    backend: str = "piper"
    audio: AudioConfig = field(default_factory=AudioConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    voices: dict[str, str] = field(default_factory=dict)
    prosody: dict[str, ProsodyConfig] = field(default_factory=dict)
    narrator: NarratorConfig = field(default_factory=NarratorConfig)

    # NEW field
    voice_management: VoiceManagementConfig = field(
        default_factory=VoiceManagementConfig
    )
```

Update `_from_dict()` to parse `voice_management` section:

```python
@classmethod
def _from_dict(cls, data: dict) -> "Config":
    # ... existing extraction ...
    vm_data = data.get("voice_management", {})

    # Build voice management config
    vm_config = VoiceManagementConfig(**vm_data) if vm_data else VoiceManagementConfig()

    return cls(
        backend=data.get("backend", "piper"),
        audio=audio_config,
        timing=timing_config,
        voices=voices_data,
        prosody=prosody_configs,
        narrator=narrator_config,
        voice_management=vm_config,  # NEW
    )
```

Add validation for `VoiceManagementConfig`:

```python
def validate(self) -> list[str]:
    errors = []
    # ... existing validation ...

    # Validate voice management settings
    if self.voice_management.max_concurrent_downloads <= 0:
        errors.append(
            f"Invalid max_concurrent_downloads: {self.voice_management.max_concurrent_downloads}. "
            "Must be positive."
        )

    # Validate bulk download quality if specified
    valid_qualities = ("x-low", "low", "medium", "high", "x-high")
    if (
        self.voice_management.bulk_download_quality
        and self.voice_management.bulk_download_quality not in valid_qualities
    ):
        errors.append(
            f"Invalid bulk_download_quality: {self.voice_management.bulk_download_quality}. "
            f"Must be one of {valid_qualities}."
        )

    return errors
```

---

## 3. CLI Changes (src/drinkingfountain/cli.py)

### New Command: `drinkingfountain voices download-bulk`

```python
@voices.command("download-bulk")
@click.option(
    "--language",
    type=str,
    help="Language code (e.g., en_US, fr_FR). If not provided, uses config default.",
)
@click.option(
    "--quality",
    type=click.Choice(["x-low", "low", "medium", "high", "x-high"], case_sensitive=False),
    help="Quality level. If not provided, uses config default.",
)
@click.option(
    "--max-workers",
    type=int,
    help="Maximum parallel downloads. If not provided, uses config default.",
)
@click.option(
    "--stop-on-error",
    is_flag=True,
    help="Stop all downloads if any fail (default: continue on errors).",
)
@click.option(
    "--voices-dir",
    type=click.Path(),
    help="Directory to download to",
)
def voices_download_bulk(
    language: str | None,
    quality: str | None,
    max_workers: int | None,
    stop_on_error: bool,
    voices_dir: str | None,
) -> None:
    """Download all voices for a language and quality in parallel.

    This command queries Piper's voice catalog, filters by language and quality,
    and downloads matching voices in parallel. It provides progress feedback
    and continues on errors by default.

    Examples:

        drinkingfountain voices download-bulk --language en_US --quality medium

        drinkingfountain voices download-bulk --language fr_FR --quality high --max-workers 8

    Configuration: You can set defaults in the config file under voice_management:

        voice_management:
          bulk_download_language: en_US
          bulk_download_quality: medium
          max_concurrent_downloads: 4
    """
    try:
        # Load config to get defaults
        config_obj = Config.load()
        vm_config = config_obj.voice_management

        # Resolve parameters from CLI or config
        resolved_language = language or vm_config.bulk_download_language
        resolved_quality = quality
        resolved_max_workers = max_workers or vm_config.max_concurrent_downloads

        if not resolved_language:
            click.echo(
                "Error: Language is required. Specify --language or set "
                "voice_management.bulk_download_language in config.",
                err=True,
            )
            sys.exit(1)

        if not resolved_quality:
            click.echo(
                "Error: Quality is required. Specify --quality or set "
                "voice_management.bulk_download_quality in config.",
                err=True,
            )
            sys.exit(1)

        # Initialize backend
        voices_dir_path = Path(voices_dir) if voices_dir else None
        piper = PiperTTSBackend(voices_dir=voices_dir_path, max_text_length=500)

        # Fetch available voices
        click.echo(f"Fetching available voices from Piper...")
        all_available = piper.list_available_voices()

        # Filter by language prefix and quality suffix
        # Voice ID format: {language}-{name}-{quality}
        language_prefix = resolved_language + "-"
        quality_suffix = "-" + resolved_quality

        matching_voices = [
            v
            for v in all_available
            if v.startswith(language_prefix) and v.endswith(quality_suffix)
        ]

        if not matching_voices:
            click.echo(
                f"No voices found for language '{resolved_language}' with quality '{resolved_quality}'."
            )
            click.echo("Available languages/qualities can be seen with:")
            click.echo("  drinkingfountain voices available")
            sys.exit(1)

        click.echo(
            f"Found {len(matching_voices)} voice(s) to download for "
            f"{resolved_language} ({resolved_quality}):"
        )
        for voice in sorted(matching_voices):
            click.echo(f"  - {voice}")

        # Confirm before proceeding
        if not click.confirm("Proceed with bulk download?"):
            click.echo("Cancelled.")
            sys.exit(0)

        # Progress callback
        completed_count = 0
        def progress_callback(completed: int, total: int, current: str) -> None:
            """Update progress display."""
            # Clear line and show progress
            click.echo(f"\rProgress: {completed}/{total} - Downloading '{current}'...", nl=False)

        # Perform bulk download
        click.echo("\nStarting downloads...")
        successful, failed = piper.download_voices_bulk(
            matching_voices,
            max_workers=resolved_max_workers,
            progress_callback=progress_callback,
            stop_on_error=stop_on_error,
        )

        # Final summary
        click.echo(f"\n\n✓ Bulk download complete!")
        click.echo(f"  Successful: {successful}")
        if failed > 0:
            click.echo(f"  Failed: {failed}")
            click.echo("  Check logs for details.")

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        if verbose:  # Need to capture verbose from main? This is a subcommand
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)
```

**Note:** The `verbose` flag isn't available in this subcommand. We should either:
- Add `@click.pass_context` and use `ctx.obj` to get verbose from main group
- Or just always show traceback on error (simpler)

Better approach: Use `@click.pass_context` and inherit verbose from parent:

```python
@voices.command("download-bulk")
@click.pass_context
@click.option(...)
def voices_download_bulk(ctx: click.Context, ...):
    verbose = ctx.obj.get("verbose", False) if ctx.obj else False
    # use verbose in exception handling
```

But the current CLI doesn't use `Context` objects for state. Simpler: add a `--verbose` flag to the subcommand itself, or just log errors without traceback unless a flag is given. For now, we can omit traceback.

### Modified Command: `drinkingfountain render`

Add `--verbose` flag already exists. Need to ensure `VoiceManager` is properly initialized with narrator exclusion.

The render command already creates `VoiceManager` and passes it to `RenderService`. The changes in `RenderService` will automatically:
1. Call `voice_mgr.start_render()` at the beginning of `render()`
2. Set narrator voice via `voice_mgr.set_narrator_voice()` if narrator enabled

No CLI changes needed for the caching/narrator features - they're automatic.

---

## 4. Voice Assignment Algorithm with Caching and Exclusion

### Algorithm: `VoiceManager.get_voice_for_character(character)`

```
Input: character (string)
Output: voice_id (string)

ALGORITHM:
1. IF character is in _char_voice_cache:
     RETURN _char_voice_cache[character]

2. IF character is in _overrides:
     voice = _overrides[character]
   ELSE IF _default_voice is set:
     voice = _default_voice
   ELSE:
     // Auto-assignment from pool
     IF _auto_pool is empty:
       voices = backend.list_voices()
       IF voices is empty:
         RAISE RuntimeError("No voices available...")

       // Exclude narrator voice from pool
       IF _narrator_voice is set:
         voices = [v for v in voices if v != _narrator_voice]
         IF voices is empty AFTER exclusion:
           RAISE ValueError("No voices available for character assignment...")

       _auto_pool = copy of voices

     voice = random.choice(_auto_pool)

3. Cache result: _char_voice_cache[character] = voice
4. RETURN voice
```

### Invariants

- **Consistency**: Once `get_voice_for_character(char)` is called, the returned voice is cached and will be returned for all subsequent calls with the same `char` until `start_render()` is invoked.
- **Exclusion**: The narrator voice (if set) is never in `_auto_pool`, so it cannot be auto-assigned to any character.
- **Override Priority**: Overrides always win, regardless of narrator or cache.
- **Cache Isolation**: Each render starts with a fresh cache via `start_render()`, allowing different renders to use different random assignments.

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Character has override | Override used, cached. Narrator exclusion doesn't apply (explicit override can use narrator voice if desired, though not recommended). |
| Default voice set | Default used for all non-override characters, cached. |
| Auto-assignment with no narrator | Random from all available voices, cached per character. |
| Auto-assignment with narrator | Random from available voices **excluding** narrator voice, cached per character. |
| Auto pool becomes empty after narrator exclusion | `ValueError` raised. User must either add more voices or assign specific voices to characters. |
| `start_render()` called mid-render | Cache cleared. Subsequent `get_voice_for_character()` calls may reassign voices (unlikely to happen in practice, but safe). |
| `download_voice()` called during render | Auto pool and character cache cleared to include new voice. |

---

## 5. Bulk Download Algorithm

### Algorithm: `PiperTTSBackend.download_voices_bulk(voices, max_workers, progress_callback, stop_on_error)`

```
Input: voices (list of strings), max_workers (int), progress_callback (func or None), stop_on_error (bool)
Output: (successful_count, failed_count)

ALGORITHM:
1. IF voices is empty: RETURN (0, 0)

2. Initialize:
     completed = 0
     failed = 0
     errors = empty list

3. Create ThreadPoolExecutor with max_workers

4. Submit _download_single_voice(voice) for each voice → future_to_voice map

5. FOR each future in as_completed(future_to_voice):
     voice = future_to_voice[future]

     TRY:
       future.result()  // blocks, raises if download failed
       completed += 1
       logger.info("Successfully downloaded voice '%s'", voice)

     CATCH Exception as e:
       failed += 1
       errors.append((voice, str(e)))
       logger.error("Failed to download voice '%s': %s", voice, e)

       IF stop_on_error:
         Cancel all remaining futures
         RAISE RuntimeError("Bulk download stopped due to error: ...")

     IF progress_callback is not None:
       TRY:
         progress_callback(completed + failed, total, voice)
       CATCH Exception as e:
         logger.warning("Progress callback raised: %s", e)

6. Log summary:
     IF failed > 0:
       Log warning with counts
       Log first 10 errors
     ELSE:
       Log info success

7. RETURN (completed, failed)
```

### Helper: `_download_single_voice(voice)`

```
1. Verify PIPER_AVAILABLE, else raise RuntimeError
2. Ensure download_dir exists
3. Run subprocess:
     [sys.executable, "-m", "piper.download_voices", voice, "--download-dir", str(download_dir)]
   with check=True
4. On CalledProcessError, parse error and raise appropriate RuntimeError
5. On other exceptions, raise RuntimeError
```

### Progress Display (CLI)

The CLI uses a simple callback that updates the same line:

```python
def progress_callback(completed: int, total: int, current: str) -> None:
    click.echo(f"\rProgress: {completed}/{total} - Downloading '{current}'...", nl=False)

# After completion:
click.echo("\n\n✓ Bulk download complete!")
```

### Error Handling Strategy

- **`stop_on_error=False` (default)**: Continue downloading all voices even if some fail. Returns counts; user can retry only failed ones by checking logs.
- **`stop_on_error=True`**: Abort all downloads on first failure. Useful for CI or when you need all-or-nothing.
- Individual download failures are logged but don't crash the bulk operation unless `stop_on_error=True`.
- The CLI shows a summary of successes/failures and points to logs for details.

---

## 6. Configuration Changes

### New Config File Sections

#### `voice_management` (optional)

```yaml
voice_management:
  bulk_download_language: en_US        # Default language for bulk downloads
  bulk_download_quality: medium        # Default quality: x-low, low, medium, high, x-high
  max_concurrent_downloads: 4          # Parallel download threads
```

Example full config:

```yaml
backend: piper
audio:
  sample_rate: 22050
  channels: mono
  normalize: true
timing:
  pause_between_lines: 0.3
  pause_after_scene_heading: 1.0
  pause_between_scenes: 2.0
voices:
  NARRATOR: en_US-amy-medium
  JOHN: en_US-john-medium
narrator:
  enabled: true
  voice: null                # auto-select first available
  expand_int_ext: true
voice_management:
  bulk_download_language: en_US
  bulk_download_quality: medium
  max_concurrent_downloads: 4
```

### Backward Compatibility

- All new fields have defaults (`None` or sensible numbers)
- Existing configs without `voice_management` will work unchanged
- The caching and narrator exclusion features are automatic and require no config changes
- Bulk download command can be used without config (must provide `--language` and `--quality` flags)

---

## 7. Edge Cases and Error Handling

### 7.1 Narrator Exclusion Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Narrator voice not installed | RenderService logs warning and disables narrator. `VoiceManager.set_narrator_voice(None)` effectively. |
| Narrator voice explicitly overridden for a character | Override takes precedence; character gets narrator voice anyway. This is allowed (though unusual). The exclusion only applies to auto-assignment pool. |
| Only one voice installed and it's the narrator | Auto-assignment pool becomes empty → `ValueError` raised with clear message suggesting to add more voices or assign overrides. |
| Narrator voice changes between renders | `start_render()` resets cache; new narrator voice set at each render. No stale state. |
| `set_narrator_voice()` called multiple times | Last call wins; auto pool cleared each time. |

### 7.2 Bulk Download Edge Cases

| Edge Case | Handling |
|-----------|----------|
| No voices match language+quality | CLI prints friendly message and exits with error code. |
| Network failure during one download | That voice fails, others continue. Summary shows failures. |
| Piper not installed | `RuntimeError` raised immediately before any downloads. |
| Invalid voice ID in list (shouldn't happen from Piper catalog) | Download fails, logged, continues. |
| `voices_dir` not writable | Subprocess raises `CalledProcessError` or `OSError`; caught and counted as failure. |
| User interrupts with Ctrl+C | ThreadPoolExecutor cancels remaining tasks; CLI exits with non-zero code. |
| Very large number of voices (e.g., 100+) | Thread pool limits concurrency; progress callback updates frequently. |
| Progress callback raises exception | Logged as warning, download continues. |

### 7.3 Caching Edge Cases

| Edge Case | Handling |
|-----------|----------|
| `get_voice_for_character()` called with different case (e.g., "John" vs "JOHN") | Character names are case-sensitive as in script. Overrides should match exact case. Consider normalizing? **Decision**: Keep case-sensitive to allow distinct characters that only differ by case (rare but possible). Document that character names are case-sensitive. |
| Voice deleted from disk after assignment but before synthesis | `generate_audio()` will raise `FileNotFoundError`. Handled by RenderService with clear error message. |
| New voice downloaded during render | `download_voice()` clears auto pool and character cache. This could cause inconsistency if done mid-render. **Mitigation**: Not expected to happen during render; downloads happen before rendering. If it does, cache reset is safe. |
| `start_render()` not called before first `get_voice_for_character()` | First render effectively starts without explicit call. But RenderService now calls it, so OK. For other uses, we could auto-call on first get? **Decision**: Require explicit `start_render()` to be safe and explicit. RenderService handles it. |

---

## 8. Migration Path from Current Implementation

### Step 1: Add New Fields and Methods (Backward Compatible)

1. Add `_char_voice_cache` and `_narrator_voice` to `VoiceManager.__init__()` with empty/None defaults.
2. Add `start_render()` method (no-op if not called, but RenderService will call it).
3. Add `set_narrator_voice()` method (no-op if not called).
4. Modify `get_voice_for_character()` to use caching and exclusion (existing behavior unchanged if cache miss every time, which is what happens without `start_render()`).

**Result**: Existing code continues to work, but without consistency guarantees until `start_render()` is called.

### Step 2: Update RenderService

- Add `self.voice_mgr.start_render()` at the beginning of `render()`.
- After determining narrator voice, add `self.voice_mgr.set_narrator_voice(narrator_voice)`.

**Result**: New behavior activated for all renders. No other changes needed.

### Step 3: Add Bulk Download to PiperTTSBackend

- Add `download_voices_bulk()` and `_download_single_voice()` methods.
- No changes to existing methods.

**Result**: Bulk download is additive; existing single-voice download unchanged.

### Step 4: Add CLI Command

- Add `voices_download_bulk()` function.
- Register with `@voices.command("download-bulk")`.

**Result**: New command available; old commands unchanged.

### Step 5: Update Config

- Add `VoiceManagementConfig` dataclass.
- Add `voice_management` field to `Config` with default `VoiceManagementConfig()`.
- Update `_from_dict()` to parse optional `voice_management` section.
- Add validation for new fields.

**Result**: Old configs work; new configs can set defaults for bulk download.

### Step 6: Tests

- Update `TestVoiceManager` to test caching and narrator exclusion.
- Add tests for `download_voices_bulk()` (mock ThreadPoolExecutor and subprocess).
- Add integration test for render with multiple dialogue lines verifying same character gets same voice.
- Add test for narrator exclusion edge cases.

---

## 9. Impact on Existing Tests and Required New Tests

### 9.1 Existing Tests to Update

**File: `tests/test_tts.py`**

- `TestVoiceManager` tests currently assume each call to `get_voice_for_character()` with auto-assignment may return different values. Need to update:
  - Tests that rely on auto-assignment randomness should now account for caching. For example, `test_get_voice_for_character_auto_assigns_if_no_default` should call `start_render()` first or test cache behavior explicitly.
  - Add tests for `start_render()` clearing cache.
  - Add tests for `set_narrator_voice()` and its effect on auto pool.

**Suggested updates:**

```python
def test_get_voice_for_character_caches_auto_assignment(self) -> None:
    """Test that auto-assigned voice is cached for the character."""
    mock_backend = MagicMock(spec=TTSBackend)
    mock_backend.list_voices.return_value = ["voice1", "voice2"]
    manager = VoiceManager(mock_backend)
    manager.start_render()  # Start fresh render

    # First call should pick and cache
    voice1 = manager.get_voice_for_character("Charlie")
    assert voice1 in {"voice1", "voice2"}

    # Second call should return same cached voice
    voice2 = manager.get_voice_for_character("Charlie")
    assert voice2 == voice1

def test_start_render_clears_cache(self) -> None:
    """Test that start_render() resets character voice cache."""
    mock_backend = MagicMock(spec=TTSBackend)
    mock_backend.list_voices.return_value = ["voice1", "voice2"]
    manager = VoiceManager(mock_backend)
    manager.start_render()

    # Assign a voice
    v1 = manager.get_voice_for_character("Alice")
    assert "Alice" in manager._char_voice_cache

    # New render clears cache
    manager.start_render()
    assert manager._char_voice_cache == {}
    # Should be able to assign different voice (though random)
    v2 = manager.get_voice_for_character("Alice")
    # Could be same or different, but cache is fresh
    assert v2 in {"voice1", "voice2"}

def test_narrator_voice_excluded_from_auto_pool(self) -> None:
    """Test that narrator voice is not in auto-assignment pool."""
    mock_backend = MagicMock(spec=TTSBackend)
    mock_backend.list_voices.return_value = ["v1", "narrator_voice", "v2"]
    manager = VoiceManager(mock_backend)
    manager.start_render()
    manager.set_narrator_voice("narrator_voice")

    # Auto-assign should pick from v1 or v2 only
    voice = manager.get_voice_for_character("Bob")
    assert voice in {"v1", "v2"}
    assert voice != "narrator_voice"

def test_narrator_exclusion_raises_if_pool_empty(self) -> None:
    """Test that ValueError raised if all voices are excluded."""
    mock_backend = MagicMock(spec=TTSBackend)
    mock_backend.list_voices.return_value = ["narrator_only"]
    manager = VoiceManager(mock_backend)
    manager.start_render()
    manager.set_narrator_voice("narrator_only")

    with pytest.raises(ValueError, match="No voices available for character assignment"):
        manager.get_voice_for_character("Anyone")

def test_override_can_use_narrator_voice(self) -> None:
    """Test that overrides can still use narrator voice (explicit choice)."""
    mock_backend = MagicMock(spec=TTSBackend)
    mock_backend.list_voices.return_value = ["v1", "narrator_voice"]
    manager = VoiceManager(mock_backend)
    manager.start_render()
    manager.set_narrator_voice("narrator_voice")
    manager.set_character_voice("Alice", "narrator_voice")  # Explicit override

    # Should use narrator voice despite exclusion
    assert manager.get_voice_for_character("Alice") == "narrator_voice"
```

### 9.2 New Tests to Add

**File: `tests/test_tts.py`**

- `TestPiperTTSBackend.download_voices_bulk()`
  - Test parallel downloads with mocked `ThreadPoolExecutor` and `_download_single_voice`
  - Test progress callback invocation
  - Test `stop_on_error=True` stops remaining downloads
  - Test `stop_on_error=False` continues on failures
  - Test empty list returns (0,0)
  - Test that successful count and failed count are correct
  - Test that exceptions from individual downloads are caught and logged

**File: `tests/test_integration.py` or new `tests/test_voice_management.py`**

- Integration test: Render a script with multiple dialogue lines for the same character, verify same voice used (mock TTS backend to track which voice called).
- Integration test: Render with narrator enabled, verify narrator voice not assigned to any character (check auto-assigned voices).
- Test `RenderService` calls `voice_mgr.start_render()` and `voice_mgr.set_narrator_voice()`.

**File: `tests/test_cli.py`**

- Test `voices download-bulk` command:
  - Test with mocked `list_available_voices` and `download_voices_bulk`
  - Test language/quality resolution from CLI vs config
  - Test error when language/quality missing
  - Test confirmation prompt
  - Test progress display
  - Test summary output

---

## 10. Summary of Changes

### Files to Modify

| File | Changes |
|------|---------|
| `src/drinkingfountain/voices/manager.py` | Add `_char_voice_cache`, `_narrator_voice`, `start_render()`, `set_narrator_voice()`, modify `get_voice_for_character()` |
| `src/drinkingfountain/tts/piper.py` | Add `download_voices_bulk()` and `_download_single_voice()` |
| `src/drinkingfountain/services.py` | Call `voice_mgr.start_render()` and `voice_mgr.set_narrator_voice()` in `render()` |
| `src/drinkingfountain/config/settings.py` | Add `VoiceManagementConfig` and `voice_management` field to `Config` |
| `src/drinkingfountain/cli.py` | Add `voices download-bulk` command |
| `tests/test_tts.py` | Update VoiceManager tests, add bulk download tests |
| `tests/test_integration.py` or new | Add integration tests for caching and narrator exclusion |
| `tests/test_cli.py` | Add tests for new CLI command |

### New Files

None required, but consider:
- `tests/test_voice_manager_cache.py` (if splitting from test_tts.py)

### API Stability

- All existing public APIs remain unchanged (backward compatible)
- New methods are additions: `VoiceManager.start_render()`, `VoiceManager.set_narrator_voice()`, `PiperTTSBackend.download_voices_bulk()`
- Config additions are additive with defaults

---

## 11. Pseudocode Summary

### VoiceManager.get_voice_for_character()

```python
def get_voice_for_character(self, character: str) -> str:
    # 1. Check cache
    if character in self._char_voice_cache:
        return self._char_voice_cache[character]

    # 2. Determine voice
    if character in self._overrides:
        voice = self._overrides[character]
    elif self._default_voice:
        voice = self._default_voice
    else:
        # Build auto pool (with exclusion)
        if not self._auto_pool:
            voices = self.backend.list_voices()
            if not voices:
                raise RuntimeError("No voices available...")
            # Exclude narrator
            if self._narrator_voice:
                voices = [v for v in voices if v != self._narrator_voice]
                if not voices:
                    raise ValueError("No voices available for character assignment...")
            self._auto_pool = voices.copy()
        voice = random.choice(self._auto_pool)

    # 3. Cache and return
    self._char_voice_cache[character] = voice
    return voice
```

### PiperTTSBackend.download_voices_bulk()

```python
def download_voices_bulk(self, voices, max_workers=4, progress_callback=None, stop_on_error=False):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(self._download_single_voice, v): v for v in voices}
        completed = failed = 0
        for future in as_completed(futies):
            voice = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as e:
                failed += 1
                if stop_on_error:
                    for f in futures: f.cancel()
                    raise
            if progress_callback:
                progress_callback(completed+failed, len(voices), voice)
    return (completed, failed)
```

---

## 12. Conclusion

This design provides:

1. **Consistent voice assignment** via per-character caching within a render
2. **Narrator voice isolation** by excluding it from auto-assignment pool
3. **Bulk voice download** with parallel downloads, progress, and robust error handling

All features are backward compatible and require minimal changes to existing code. The implementation is straightforward and well-tested.
