# DrinkingFountain

**Convert Fountain-format screenplays to audio plays using local TTS models**

DrinkingFountain is a command-line tool that transforms Fountain screenplay files into fully narrated audio productions. It uses Piper TTS for high-quality, offline text-to-speech synthesis, giving you complete control over voice selection, timing, and audio output—all processed locally on your machine.

## Key Features

- **Local TTS**: No cloud services required—everything runs on your computer
- **Fountain Format**: Full support for the standard screenplay format ([fountain.io](https://fountain.io))
- **Configurable Voices**: Assign specific voices to characters via YAML config or CLI
- **Flexible Timing**: Adjustable pauses between lines, scenes, and headings
- **Audio Control**: Sample rate, channel configuration, and loudness normalization
- **Voice Management**: List, download, and test voice models from HuggingFace
- **Smart Chunking**: Automatic handling of long dialogue lines
- **Multiple Output Formats**: Export to WAV or MP3 (requires ffmpeg)
- **Web UI**: Paste or upload scripts, render in the browser, and follow synchronized playback
- **Direct Playback**: Play audio directly through the system's default audio device (requires simpleaudio)

---

## Installation

### Quick Install (Recommended)

We provide automated installers for a hassle-free setup:

**macOS / Linux:**
```bash
bash install.sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

The installer will:
- ✓ Check Python version (requires 3.10+)
- ✓ Set up a virtual environment (optional but recommended)
- ✓ Install all dependencies
- ✓ Check for and help install ffmpeg (for MP3 export)
- ✓ Install simpleaudio (for direct playback)
- ✓ Download a default voice model
- ✓ Create a sample configuration file
- ✓ Verify the installation

### Manual Installation

If you prefer to install manually or the automated installer doesn't work for your system:

#### Prerequisites

- **Python**: 3.10 or newer
- **Package manager**: `uv` (recommended) or `pip`
- **ffmpeg**: Required for MP3 export (optional if you only need WAV)
- **simpleaudio**: Required for audio playback through speakers

#### Installing ffmpeg

- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt-get install ffmpeg` (Debian/Ubuntu) or `sudo dnf install ffmpeg` (Fedora)
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

#### Install DrinkingFountain

Using **uv** (recommended):
```bash
uv sync
```

Using **pip**:
```bash
pip install -e .
```

#### Download Voice Models

At least one voice model is required. Download your first voice:

```bash
drinkingfountain voices download en_US-amy-medium
```

See [Voice Models](#voice-models) for more options.

For detailed installation instructions, troubleshooting, and uninstallation, see [INSTALL.md](INSTALL.md).

---

## Quick Start

1. **Create a Fountain script** (e.g., `script.fountain`):

```fountain
INT. COFFEE SHOP - DAY

JOHN
(sipping coffee)
This is pretty good.

SARAH
I know, right? The new blend is amazing.

JOHN
We should come here more often.
```

2. **Render to audio**:

**Option A: Save to a file** (works without simpleaudio):

```bash
drinkingfountain render script.fountain -o output.wav
```

**Option B: Play through speakers** (requires simpleaudio):

```bash
drinkingfountain render script.fountain
```

**Option C: Use the web UI**:

```bash
drinkingfountain-web
```

Then open the local URL printed by the command, paste or upload your Fountain script, and click **Render Audio**.

That's it! For more control, read on.

---

## Configuration

DrinkingFountain looks for configuration files in this order:

1. Path specified with `--config` option
2. `./drinkingfountain.yaml` (current directory)
3. `~/.config/drinkingfountain/config.yaml` (user config)
4. If none found, defaults are used

### Example Configuration

Create `drinkingfountain.yaml`:

```yaml
# TTS backend to use (currently only "piper" is implemented)
backend: piper

# Audio output settings
audio:
  sample_rate: 22050      # 22050 or 44100 Hz
  channels: mono          # "mono" or "stereo"
  normalize: true         # Normalize loudness
  target_level: -3.0      # Target dBFS (negative value)

# Timing and pauses (in seconds)
timing:
  pause_between_lines: 0.3      # Pause after each dialogue line
  pause_after_scene_heading: 1.0  # Pause after scene heading
  pause_between_scenes: 2.0      # Pause when entering new scene

# Voice management settings
voice_management:
  bulk_download_language: en_US
  bulk_download_quality: medium
  max_concurrent_downloads: 3

# Character voice assignments
# Map character names (exactly as in script) to voice IDs
voices:
  JOHN: en_US-john-medium
  SARAH: en_US-sarah-medium
  NARRATOR: en_US-amy-medium

# Prosody adjustments for parenthetical cues
# (Note: Not yet implemented—planned for future release)
prosody:
  (whispering):
    speed: 0.8
    pitch: 0.9
    volume: 0.6
  (shouting):
    speed: 1.2
    pitch: 1.3
    volume: 1.4
```

### Voice Mapping

The `voices` section lets you assign specific Piper voice models to characters. Character names must match exactly as they appear in the Fountain script (case-sensitive).

**Overrides**: Explicit voice assignments always take precedence and work exactly as before.

**Auto-assignment**: For characters without explicit mapping:
- A voice is randomly selected from the available voices (excluding the narrator voice if one is configured)
- The selection is cached per character and reused consistently across all scenes
- This ensures character voice consistency throughout the production

**Narrator handling**: If you have a `NARRATOR` role in your script:
- The narrator's voice is reserved and will never be auto-assigned to any character
- You must explicitly assign a voice to `NARRATOR` in the config if you want narration
- If only one voice is available and a narrator is detected, the narrator role is automatically disabled to avoid conflicts

**Default voice**: If you set a default voice via `VoiceManager.set_default_voice()`, it will be used for any character without explicit mapping, provided no other voices are available.

### Audio Settings

- **sample_rate**: Higher values mean better quality but larger files. 22050 Hz is sufficient for speech; use 44100 Hz for music or higher fidelity.
- **channels**: Mono uses half the storage of stereo and is perfectly fine for voice-only content.
- **normalize**: Ensures consistent loudness throughout the output. Recommended: `true`.
- **target_level**: Normalization target in dBFS. -3.0 dB is a safe, broadcast-compliant level.

### Timing Settings

Fine-tune the pacing of your audio production:

- **pause_between_lines**: Gap between consecutive dialogue lines (default: 0.3s)
- **pause_after_scene_heading**: Silence after a scene heading before first dialogue (default: 1.0s)
- **pause_between_scenes**: Extra pause when transitioning between scenes (default: 2.0s)

All timing values are in seconds and can be fractional (e.g., `0.25`).

---

## Voice Management

DrinkingFountain includes advanced voice management features that ensure consistent character voices across your entire production and simplify voice model management.

### Consistent Voice Assignment

Characters now maintain the same voice across all scenes in a render. When a voice is assigned to a character (either via explicit mapping or auto-assignment), that choice is cached and reused consistently throughout the entire script. This creates a more professional and coherent listening experience, as characters don't suddenly sound different when they appear in later scenes.

### Narrator Voice Isolation

The narrator's voice is automatically reserved and will never be auto-assigned to any character. This ensures that if you have a NARRATOR role in your script, its voice assignment remains exclusively yours to configure. The narrator voice is completely excluded from the pool of available voices during character auto-assignment.

### Voice Caching

Voice assignments are cached per character during a render. This means:
- The first time a character appears, a voice is selected (either from explicit mapping or randomly from available voices)
- That same voice is used for all subsequent appearances of that character
- The cache is cleared between renders, allowing you to change assignments for next render

This caching happens transparently and doesn't require any configuration.

### Bulk Voice Download

Download multiple voice models efficiently with the new bulk download command.

#### Command: `drinkingfountain voices download-bulk`

Downloads all available voice models for a specific language and quality from the Piper catalog.

```bash
drinkingfountain voices download-bulk [OPTIONS]
```

**Options**:
- `-l, --language CODE`: Language code (e.g., `en_US`, `fr_FR`). Required.
- `-q, --quality {x-low,low,medium,high,x-high}`: Quality level. Default: `medium`.
- `-w, --max-workers N`: Maximum concurrent downloads. Default: `3`.
- `--stop-on-error`: Stop if any download fails (default: continue on error)
- `--voices-dir PATH`: Directory to store voices (overrides default)

**Configuration defaults**:
You can set default values in `.drinkingfountain.yaml` to avoid repeating options:

```yaml
voice_management:
  bulk_download_language: en_US
  bulk_download_quality: medium
  max_concurrent_downloads: 3
```

With these defaults, you can simply run `drinkingfountain voices download-bulk` without options.

**Examples**:

Download all English (US) voices at medium quality:
```bash
drinkingfountain voices download-bulk --language en_US --quality medium
```

Download French voices with 5 concurrent workers, stopping on errors:
```bash
drinkingfountain voices download-bulk -l fr_FR -w 5 --stop-on-error
```

Use config defaults (if set in `.drinkingfountain.yaml`):
```bash
drinkingfountain voices download-bulk
```

**What it does**: This command queries the Piper voice catalog, filters by the specified language and quality, and downloads all matching voice models in parallel. It's useful for setting up a complete voice library for a particular language or quality tier.

---

### Backward Compatibility

All new voice management features are fully backward compatible:
- Existing configuration files work unchanged
- Voice assignment overrides continue to function as before
- The narrator isolation and caching are automatic—no configuration needed
- Bulk download is an optional CLI command, not required for normal operation

You can adopt these features gradually without disrupting your existing workflow.

---

## Web UI

DrinkingFountain includes a local Flask web interface for users who prefer working in a browser. It uses the same parser, voice assignment, TTS cache, narrator behavior, and audio renderer as the CLI.

The web UI is intended for local use on your own machine. It starts a development server bound to `127.0.0.1`, so other machines on your network cannot access it by default.

### Prerequisites

Before launching the web UI, make sure the project is installed and at least one Piper voice is available:

```bash
drinkingfountain voices list
```

If no voices are installed, download one:

```bash
drinkingfountain voices download en_US-amy-medium
```

For better character variety, download several voices:

```bash
drinkingfountain voices download-bulk --language en_US --quality medium
```

MP3 output also requires `ffmpeg`. WAV output works without `ffmpeg`.

### Launching the Web UI

From the project environment or after installation, run:

```bash
drinkingfountain-web
```

You can also launch it as a module:

```bash
python -m drinkingfountain.web
```

The server prints a local URL:

```text
Running on http://127.0.0.1:5000
```

Open that URL in your browser. If port `5000` is already in use, DrinkingFountain automatically starts on the next available local port and prints that URL instead. A `403 Forbidden` page at `127.0.0.1:5000` usually means another macOS service, commonly AirPlay Receiver, is answering on port `5000`; use the URL printed by `drinkingfountain-web`.

Stop the server with `Ctrl+C` in the terminal.

### Rendering a Script

1. Paste Fountain text into the **Fountain Script** field, or choose a `.fountain` or `.txt` file with the upload control.
2. Optional: open **Audio Settings** and choose sample rate, channel mode, and output format.
3. Optional: open **Timing** and adjust pauses between lines, after scene headings, and between scenes.
4. Optional: open **Narrator** to enable or disable narrated scene headings/action, expand `INT./EXT.`, or choose a narrator voice.
5. Optional: open **Character Voice Overrides** to map a character name to a specific installed voice.
6. Click **Render Audio**.

When rendering finishes, the page shows an audio player and a synchronized script view. The currently playing script block is highlighted as audio plays. Click any rendered script block to seek to that point in the audio.

### Web UI Settings

Most form settings mirror the YAML configuration:

- **Sample Rate**: fixed at `44100` Hz for browser playback compatibility.
- **Channels**: `mono` or `stereo`. Mono is recommended for voice-only renders.
- **Output Format**: `wav` or `mp3`. MP3 requires `ffmpeg`.
- **Timing**: pause values are seconds and may be fractional, such as `0.25`.
- **Narrator Voice**: leave blank for automatic selection, or choose an installed voice.
- **Voice Overrides**: character names must match the Fountain script names exactly, including capitalization.

The web UI uses the shared TTS cache at `~/.cache/drinkingfountain/tts`, so repeated renders of the same lines and voices are faster.

### Render Results and Expiration

Rendered files are stored in temporary files and served through local URLs such as `/audio/<render_id>` and `/timing/<render_id>`. Results expire automatically after about 30 minutes or when the local render store is full. Save any audio you want to keep before closing the browser or stopping the server.

### Web UI Troubleshooting

#### The page says no voice models are installed

Download at least one voice:

```bash
drinkingfountain voices download en_US-amy-medium
```

Then refresh the web page.

#### MP3 rendering fails

Install `ffmpeg`, or choose WAV in **Audio Settings**.

#### Rendering takes a long time

Long scripts can take minutes because TTS synthesis is CPU-bound. Repeated renders are faster when cached audio can be reused. For first tests, try a short scene before rendering a full screenplay.

#### The voice dropdown is empty

Check that voices are installed and visible to DrinkingFountain:

```bash
drinkingfountain voices list
```

If you use a custom voice directory in CLI commands, note that the current web UI uses Piper's default voice location.

---

## CLI Reference

### `drinkingfountain render`

Render a Fountain script to audio.

```bash
drinkingfountain render SCRIPT [OPTIONS]
```

**Arguments**:
- `SCRIPT`: Path to the Fountain file (required)

**Options**:
- `-o, --output PATH`: Output audio file path (optional). Format determined by extension (`.wav` or `.mp3`). If omitted, audio plays through the default audio device.
- `--config PATH`: Configuration file path
- `--voices-dir PATH`: Directory containing voice models (overrides default)
- `--cache-dir PATH`: TTS cache directory (caches synthesized audio to speed up re-runs)
- `--verbose`: Enable debug logging

**Examples**:

Save to a WAV file:
```bash
drinkingfountain render myscript.fountain -o output.wav
```

Play through speakers:
```bash
drinkingfountain render myscript.fountain
```

Save to MP3 (requires ffmpeg):
```bash
drinkingfountain render myscript.fountain -o output.mp3 --cache-dir .cache
```

### `drinkingfountain voices`

Manage voice models.

#### `drinkingfountain voices list`

List all installed voice models.

```bash
drinkingfountain voices list [--voices-dir PATH]
```

**Example output**:
```
Available voices (3):
  en_US-amy-medium
  en_US-john-high
  en_US-sarah-low
```

#### `drinkingfountain voices available`

List voice models available for download from Piper (not yet installed).

```bash
drinkingfountain voices available [OPTIONS]
```

**Options**:
- `--format {list,json}`: Output format. `list` shows a simple list (default). `json` shows detailed metadata.
- `--language CODE`: Filter by language code (e.g., `en_US`, `fr_FR`)

**Example output** (list format):
```
Available voices for download (3):
  en_US-amy-medium
  en_US-john-medium
  fr_FR-henri-medium
```

**Example output** (JSON format):
```json
[
  {
    "id": "en_US-amy-medium",
    "language": "en_US",
    "quality": "medium",
    "dataset": "libritts"
  }
]
```

#### `drinkingfountain voices download`

Download a voice model from HuggingFace.

```bash
drinkingfountain voices download VOICE_ID [--voices-dir PATH]
```

**Voice ID format**: `{language}-{name}-{quality}`

**Examples**:
```bash
drinkingfountain voices download en_US-amy-medium
drinkingfountain voices download en_GB-james-high
drinkingfountain voices download fr_FR-henri-medium
```

#### `drinkingfountain voices download-bulk`

Download all voice models for a specific language and quality from the Piper catalog.

```bash
drinkingfountain voices download-bulk [OPTIONS]
```

**Options**:
- `-l, --language CODE`: Language code (e.g., `en_US`, `fr_FR`). Required.
- `-q, --quality {x-low,low,medium,high,x-high}`: Quality level. Default: `medium`.
- `-w, --max-workers N`: Maximum concurrent downloads. Default: `3`.
- `--stop-on-error`: Stop if any download fails (default: continue on error)
- `--voices-dir PATH`: Directory to store voices (overrides default)

**Configuration defaults**:
Set defaults in `.drinkingfountain.yaml`:

```yaml
voice_management:
  bulk_download_language: en_US
  bulk_download_quality: medium
  max_concurrent_downloads: 3
```

**Examples**:

Download all English (US) voices at medium quality:
```bash
drinkingfountain voices download-bulk --language en_US --quality medium
```

Download French voices with 5 concurrent workers, stopping on errors:
```bash
drinkingfountain voices download-bulk -l fr_FR -w 5 --stop-on-error
```

Use config defaults (if set):
```bash
drinkingfountain voices download-bulk
```

#### `drinkingfountain voices test`

Generate sample audio with a voice.

```bash
drinkingfountain voices test VOICE_ID TEXT [--voices-dir PATH] [--output PATH]
```

**Examples**:
```bash
# Play through speakers (if simpleaudio installed)
drinkingfountain voices test en_US-amy-medium "Hello, this is a test."

# Save to file
drinkingfountain voices test en_US-amy-medium "Testing voice quality." -o test.wav
```

---

## Fountain Format

DrinkingFountain supports the [Fountain](https://fountain.io) screenplay format—a plain-text format for writing screenplays. Fountain is human-readable, version-control friendly, and widely used in the film industry.

### Basic Elements

- **Scene headings**: `INT. LOCATION - DAY` or `EXT. LOCATION - NIGHT`
- **Character names**: All caps on their own line
- **Dialogue**: Lines following a character name
- **Parentheticals**: `(text)` on line between character and dialogue
- **Action**: Any other text (descriptions, etc.)

### Example Script

```fountain
FADE IN:

INT. COFFEE SHOP - DAY

A cozy corner table. JOHN (30s, tired) sips his coffee.

JOHN
This is the third cup today.

SARAH (O.S.)
You have a problem.

JOHN
(looking up)
Says who?

SARAH enters, carrying a stack of books.

SARAH
Anyone with eyes.

They both laugh as the CAMERA PANS to the rain outside.

CUT TO:

EXT. STREET - NIGHT

The rain continues. Heavy.

FADE OUT.
```

**Note**: DrinkingFountain currently processes dialogue and scene headings. Action lines and transitions are included in the script structure but not spoken (they could be enabled via future configuration).

---

## Voice Models

### Where to Find Voices

Piper voice models are hosted on HuggingFace. The official repository is:
[https://huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)

Browse available voices by language, speaker, and quality.

### Naming Convention

Voice IDs follow the pattern:

```
{LANGUAGE}-{NAME}-{QUALITY}
```

- **LANGUAGE**: `en_US`, `en_GB`, `fr_FR`, `de_DE`, etc. (language + region)
- **NAME**: Speaker name (e.g., `amy`, `john`, `sarah`)
- **QUALITY**: One of: `x-low`, `low`, `medium`, `high`, `x-high`

**Examples**:
- `en_US-amy-medium` (American English, medium quality)
- `en_GB-james-high` (British English, high quality)
- `fr_FR-henri-medium` (French, medium quality)

### Quality Levels

- **x-low**: Smallest file size, lowest quality (not recommended)
- **low**: Small, decent quality
- **medium**: Good balance of quality and size (default choice)
- **high**: Larger, high quality
- **x-high**: Largest, best quality

**Recommendation**: Start with `medium` quality. If you need higher fidelity and have disk space, try `high`.

### Listing and Downloading

List installed voices:
```bash
drinkingfountain voices list
```

List all voices available for download from Piper:
```bash
drinkingfountain voices available
```

Filter by language:
```bash
drinkingfountain voices available --language en_US
```

Get detailed information in JSON format:
```bash
drinkingfountain voices available --format json
```

Download a voice:
```bash
drinkingfountain voices download en_US-amy-medium
```

Voices are stored in the Piper default directory:
- **Linux/macOS**: `~/.local/share/piper-tts/voices/`
- **Windows**: `%APPDATA%/local/share/piper-tts/voices/`

Override with `--voices-dir` if you want a custom location.

---

## Troubleshooting

### "No voices available" or "Voice model not found"

**Solution**: Download at least one voice model:
```bash
drinkingfountain voices download en_US-amy-medium
```

### MP3 export fails with "ffmpeg not found"

**Solution**: Install ffmpeg (see [Prerequisites](#prerequisites)). Alternatively, export to WAV:
```bash
drinkingfountain render script.fountain -o output.wav
```

### Long dialogue lines get cut off or produce errors

**Explanation**: Piper TTS has a maximum text length (typically ~500 characters). DrinkingFountain automatically chunks long dialogue into smaller pieces and concatenates the audio with short pauses.

**No action needed**—this is handled transparently. If you encounter issues, ensure you're using the latest version.

### Poor audio quality or robotic voice

**Possible causes**:
- Voice model quality is too low (try `high` or `x-high`)
- Voice model is corrupted or incomplete (re-download)
- Sample rate mismatch (use 22050 Hz for most Piper voices)

**Solutions**:
1. Try a different voice: `drinkingfountain voices download en_US-amy-high`
2. Check your audio settings: `sample_rate: 22050` is recommended for Piper
3. Verify the voice file exists: `ls ~/.local/share/piper-tts/voices/en_US-amy-medium.onnx`

### "No dialogue found in script"

**Cause**: The Fountain file may not have properly formatted dialogue (character names not in ALL CAPS, missing blank lines).

**Solution**: Ensure your script follows Fountain conventions:
- Character names on their own line, in ALL CAPS
- Blank line before character name
- Dialogue lines directly after character

### Audio is too quiet or too loud

**Solution**: Adjust normalization settings in config:
```yaml
audio:
  normalize: true
  target_level: -3.0  # Try -6.0 for quieter, -1.0 for louder
```

Or disable normalization and adjust manually in post.

---

## Known Limitations

### Not Yet Implemented

- **Prosody from parentheticals**: Parenthetical cues like `(whispering)` or `(shouting)` are parsed but not yet applied to TTS output. This is planned for a future release.
- **Dual dialogue**: Simultaneous dialogue (two characters speaking at once using `^` notation) is not supported. Lines are processed sequentially.
- **Non-dialogue speech**: Action lines can be narrated when the narrator is enabled. Transitions and other non-dialogue elements are not synthesized.
- **Web UI scope**: The web UI is a local single-user interface. It does not provide accounts, background render queues, saved projects, or network sharing.

### Platform-Specific Notes

- **Windows**: Voice download may require additional permissions or manual download from HuggingFace if subprocess calls fail.
- **ARM/Mac Silicon**: Piper TTS works natively on Apple Silicon. No Rosetta needed.
- **GPU acceleration**: Not currently used—all synthesis runs on CPU.

### Voice Model Availability

- Piper voice models are limited to what's available on HuggingFace. Not all languages/speakers are supported.
- Voice quality varies by language. English voices are most abundant and highest quality.

---

## Development

### Running Tests

Using **uv**:
```bash
uv run pytest
```

Using **pytest** directly:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=src/drinkingfountain
```

### Pre-commit Hooks

Install pre-commit hooks to enforce code quality:

```bash
pre-commit install
```

This runs Ruff formatting and linting on staged files.

### Project Structure

```
drinkingfountain/
├── src/drinkingfountain/
│   ├── __init__.py
│   ├── cli.py              # Command-line interface (Click)
│   ├── audio/
│   │   ├── mixer.py        # Audio mixing, pauses, normalization
│   │   └── __init__.py
│   ├── config/
│   │   ├── settings.py     # Configuration dataclasses
│   │   └── __init__.py
│   ├── parser/
│   │   ├── fountain.py     # Fountain format parser
│   │   ├── script.py       # Script data structures
│   │   └── __init__.py
│   ├── tts/
│   │   ├── base.py         # TTS backend interface
│   │   ├── piper.py        # Piper TTS implementation
│   │   ├── cache.py        # Caching wrapper
│   │   └── __init__.py
│   ├── utils/
│   │   ├── text_chunker.py # Long text splitting
│   │   └── __init__.py
│   ├── web/
│   │   ├── app.py          # Flask routes and render store
│   │   ├── templates/      # Browser UI templates
│   │   └── static/         # Web UI CSS and JavaScript
│   └── voices/
│       ├── manager.py      # Voice assignment logic
│       └── __init__.py
├── tests/                  # Test suite
├── pyproject.toml          # Project metadata and dependencies
├── .pre-commit-config.yaml # Pre-commit configuration
└── README.md               # This file
```

### Architecture Overview

1. **CLI** (`cli.py`): Entry point, parses arguments, orchestrates the pipeline
2. **Parser** (`parser/fountain.py`): Reads Fountain files into `Script` objects
3. **Config** (`config/settings.py`): Loads YAML configuration with validation
4. **VoiceManager** (`voices/manager.py`): Maps characters to voice IDs
5. **TTS Backend** (`tts/piper.py`): Generates audio via Piper, handles chunking
6. **AudioMixer** (`audio/mixer.py`): Combines segments, adds pauses, normalizes, exports
7. **Web UI** (`web/app.py`): Wraps the same services in local Flask routes and browser playback

### Adding New TTS Backends

The `TTSBackend` abstract base class (in `tts/base.py`) defines the interface:

```python
class TTSBackend(Protocol):
    def is_available(self) -> bool: ...
    def list_voices(self) -> list[str]: ...
    def download_voice(self, voice: str, target_dir: Path | None) -> None: ...
    def generate_audio(self, text: str, voice: str) -> AudioSegment: ...
```

Implement this protocol to add support for Coqui TTS, Transformers, or cloud services.

---

## License

MIT License. See `pyproject.toml` for details.

---

## Getting Help

- **Bug reports**: Open an issue on the project repository
- **Questions**: Check the [Fountain spec](https://fountain.io) for script formatting questions
- **Piper TTS**: See [Piper documentation](https://github.com/rhasspy/piper)

---

*Happy scripting, and may your table reads be ever in tune!*
