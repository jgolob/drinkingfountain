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

---

## Installation

### Prerequisites

- **Python**: 3.10 or newer
- **Package manager**: `uv` (recommended) or `pip`
- **ffmpeg**: Required for MP3 export (optional if you only need WAV)

#### Installing ffmpeg

- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt-get install ffmpeg` (Debian/Ubuntu) or `sudo dnf install ffmpeg` (Fedora)
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

### Install DrinkingFountain

Using **uv** (recommended):
```bash
uv sync
```

Using **pip**:
```bash
pip install -e .
```

### Download Voice Models

At least one voice model is required. Download your first voice:

```bash
drinkingfountain voices download en_US-amy-medium
```

See [Voice Models](#voice-models) for more options.

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

```bash
drinkingfountain render script.fountain -o output.wav
```

3. **Play the output**:

```bash
# macOS
afplay output.wav

# Linux
play output.wav

# Windows
start output.wav
```

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

The `voices` section lets you assign specific Piper voice models to characters. Character names must match exactly as they appear in the Fountain script (case-sensitive). If a character has no explicit mapping, DrinkingFountain will:

1. Use the default voice if set (via `VoiceManager.set_default_voice()`)
2. Otherwise, randomly select from available voices

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

## CLI Reference

### `drinkingfountain render`

Render a Fountain script to audio.

```bash
drinkingfountain render SCRIPT -o OUTPUT [OPTIONS]
```

**Arguments**:
- `SCRIPT`: Path to the Fountain file (required)

**Options**:
- `-o, --output PATH`: Output audio file path (required). Format determined by extension (`.wav` or `.mp3`)
- `--config PATH`: Configuration file path
- `--voices-dir PATH`: Directory containing voice models (overrides default)
- `--cache-dir PATH`: TTS cache directory (caches synthesized audio to speed up re-runs)
- `--verbose`: Enable debug logging

**Example**:
```bash
drinkingfountain render myscript.fountain -o myscript.mp3 --cache-dir .cache
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
- **Non-dialogue speech**: Action lines, transitions, and other non-dialogue elements are not synthesized. Only scene headings (if configured) and dialogue are included in the audio output.
- **GUI**: DrinkingFountain is CLI-only. No graphical interface is currently planned, but the CLI is designed to be scriptable.

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
