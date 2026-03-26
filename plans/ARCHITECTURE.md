# Drinking Fountain: Architecture & Design

## Project Overview

**Drinking Fountain** is a local TTS-powered tool that converts Fountain-format screenplays into audioplays for table reads. It uses pretrained text-to-speech models running entirely on the local machine.

## Core Requirements

1. **Input**: Fountain-format screenplay files (`.fountain` or `.txt`)
2. **Processing**: Parse script, assign voices to characters, generate speech
3. **Output**: Mixed audio file (WAV/MP3) representing a complete audioplay
4. **Local Execution**: All TTS models run locally, no API dependencies
5. **Lightweight Models**: Use small, fast pretrained TTS models

## System Architecture

```
┌─────────────────┐
│  Fountain File  │
│   (.fountain)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         Fountain Parser                     │
│  • Extract scenes, characters, dialogue    │
│  • Parse parentheticals, actions           │
│  • Build script structure tree             │
└────────┬────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         Voice Assignment Engine             │
│  • Map characters to TTS voices            │
│  • Support voice configuration/overrides   │
│  • Handle voice cloning if available       │
└────────┬────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         TTS Generation Layer                │
│  • Batch process dialogue lines            │
│  • Apply prosody adjustments                │
│  • Generate individual audio segments      │
└────────┬────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         Audio Mixing Engine                 │
│  • Add pauses between lines                │
│  • Layer sound effects (optional)          │
│  • Normalize volume levels                 │
│  • Render final mix                        │
└────────┬────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Output Audio   │
│  (.wav/.mp3)    │
└─────────────────┘
```

## Technology Stack

### Language & Package Management
- **Python 3.14** (as specified in `.python-version`)
- **uv** for dependency management and packaging

### Core Dependencies (to be added)

#### TTS Engine Options

**Option A: Piper TTS** (Recommended)
- Lightweight, fast, good quality
- ~50MB models, runs on CPU efficiently
- Simple Python API via `piper-tts` or direct binary calls
- Multiple voice support

**Option B: Coqui TTS**
- Higher quality, more features
- Larger models (200MB-2GB)
- More dependencies, slower
- Better voice cloning support

**Option C: HuggingFace Transformers + SpeechT5/VITS**
- Moderate size (~300MB-1GB)
- Pure Python, good integration
- More control over generation

**Initial Recommendation**: Start with **Piper TTS** for speed and simplicity, can add alternatives later.

#### Audio Processing
- `pydub` - Audio mixing, format conversion, effects
- `numpy` - Audio array manipulation
- `soundfile` or `librosa` - Audio I/O

#### Fountain Parsing
- Custom parser (Fountain format is relatively simple)
- Or use existing library if available (e.g., `fountain` PyPI package)

### Project Structure

```
drinkingfountain/
├── pyproject.toml          # uv config, dependencies
├── README.md               # Project documentation
├── .gitignore
├── .python-version
│
├── src/
│   └── drinkingfountain/
│       ├── __init__.py
│       ├── cli.py          # Command-line interface
│       ├── parser/
│       │   ├── __init__.py
│       │   ├── fountain.py # Fountain format parser
│       │   └── script.py   # Script data structures
│       ├── voices/
│       │   ├── __init__.py
│       │   ├── manager.py  # Voice assignment & config
│       │   └── registry.py # Available TTS backends
│       ├── tts/
│       │   ├── __init__.py
│       │   ├── base.py     # Abstract TTS interface
│       │   ├── piper.py    # Piper TTS implementation
│       │   └── cache.py    # TTS output caching
│       ├── audio/
│       │   ├── __init__.py
│       │   ├── mixer.py    # Audio mixing & effects
│       │   └── formats.py  # Audio format handling
│       └── config/
│           ├── __init__.py
│           ├── settings.py # Configuration management
│           └── voices.yaml # Voice assignments
│
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   ├── test_tts.py
│   └── test_audio.py
│
├── voices/                 # Voice model storage (gitignored)
│   └── piper/
│       ├── en_US-...       # Downloaded voice models
│       └── ...
│
├── outputs/                # Generated audio (gitignored)
│   └── ...
│
├── cache/                  # TTS cache (gitignored)
│   └── ...
│
└── scripts/
    └── download_voices.py  # Helper to download voice models
```

## Key Design Decisions

### 1. Fountain Format Parsing

Fountain is a plain-text screenplay format with conventions:
- **Character names**: UPPERCASE on their own line
- **Dialogue**: Lines following a character, indented or not
- **Parentheticals**: (in parentheses) within dialogue
- **Scene headings**: `INT.`/`EXT.` or `SCENE:` prefixes
- **Action**: Any other text blocks

The parser will:
1. Read file line-by-line
2. Detect block types based on formatting patterns
3. Build a hierarchical structure: Script → Scenes → Blocks (Dialogue, Action, etc.)
4. Extract metadata (character names, scene locations)

### 2. Voice Assignment Strategy

**Automatic Assignment**:
- First pass: Collect all character names from dialogue blocks
- Assign each character a random available voice from the TTS backend
- Optionally assign narrator voice to action blocks

**Configuration Override**:
- YAML config file mapping character names to specific voices
- Example:
  ```yaml
  voices:
    NARRATOR: en_US-amy-medium
    JOHN: en_US-john-medium
    MARY: en_US-mary-medium
  ```

**Voice Characteristics**:
- Piper voices follow naming: `{language}-{name}-{quality}`
- Quality levels: `x-low`, `low`, `medium`, `high`, `x-high`
- Allow user to specify default quality level

### 3. TTS Generation Pipeline

**Caching Strategy**:
- Hash dialogue text + voice ID + parameters
- Cache audio segments to avoid regenerating
- Cache location: `cache/{hash}.wav`

**Batch Processing**:
- Group all dialogue lines by voice
- Generate in batches to minimize model loading overhead
- Piper can process multiple lines efficiently

**Prosody Control**:
- Detect emotional cues from parentheticals: (angrily), (whispering), etc.
- Map to TTS parameters (speed, pitch, volume)
- Default adjustments:
  - `(angrily)`: +10% speed, higher pitch
  - `(sadly)`: -10% speed, lower pitch
  - `(whispering)`: -20% volume
  - `(excited)`: +15% speed, pitch variation

### 4. Audio Mixing

**Timing & Pauses**:
- Standard pause between dialogue lines: 0.3s
- Pause after scene headings: 1.0s
- Longer pauses for scene changes: 2.0s
- Pause duration configurable

**Volume Normalization**:
- Normalize all speech segments to -3dB peak
- Ensure consistent volume across different TTS outputs

**Optional Sound Effects**:
- Support for ambient sounds (rain, café, etc.)
- Configurable per scene
- Placeholder for future enhancement

**Output Formats**:
- Default: WAV (lossless)
- Optional: MP3 (requires `lame` or `ffmpeg`)
- Sample rate: 22kHz or 44.1kHz
- Mono or stereo (mono for efficiency)

### 5. Command-Line Interface

```bash
# Basic usage
drinkingfountain render script.fountain -o output.wav

# With voice configuration
drinkingfountain render script.fountain --voices voices.yaml -o output.wav

# List available voices
drinkingfountain voices list

# Download voice models
drinkingfountain voices download en_US-amy-medium

# Preview a voice
drinkingfountain voices test "en_US-amy-medium" "Hello, this is a test."

# With custom settings
drinkingfountain render script.fountain \
  --pause 0.5 \
  --quality high \
  --output-format mp3 \
  --normalize
```

### 6. Configuration Management

**Config File Locations** (in order of precedence):
1. `--config` flag
2. `./drinkingfountain.yaml`
3. `~/.config/drinkingfountain/config.yaml`

**Configuration Options**:
```yaml
# TTS backend
backend: piper

# Default voice quality
quality: medium

# Audio settings
sample_rate: 22050
channels: mono
normalize: true

# Timing (seconds)
pause_between_lines: 0.3
pause_after_scene: 1.0
pause_scene_change: 2.0

# Voice mappings
voices:
  NARRATOR: en_US-amy-medium
  # Character-specific voices

# Prosody adjustments
prosody:
  angrily:
    speed: 1.1
    pitch: 1.1
  sadly:
    speed: 0.9
    pitch: 0.9
  whispering:
    volume: 0.8
```

## Implementation Phases

### Phase 1: Foundation (Week 1)
- Set up project structure
- Implement basic Fountain parser
- Create script data structures
- Write unit tests for parser

### Phase 2: TTS Integration (Week 2)
- Integrate Piper TTS
- Implement voice management
- Add voice caching
- Test with sample scripts

### Phase 3: Audio Pipeline (Week 3)
- Implement audio mixing
- Add timing and pauses
- Volume normalization
- Format conversion

### Phase 4: CLI & Polish (Week 4)
- Build complete CLI
- Configuration file support
- Error handling and validation
- Documentation and examples

### Phase 5: Enhancements (Future)
- Voice cloning support
- Sound effects library
- GUI interface
- Real-time preview
- Multiple language support

## Performance Considerations

- **Memory**: Piper models ~50MB each, load on-demand
- **Speed**: ~2-5x real-time on modern CPU (depends on quality)
- **Disk**: Cache all generated segments to avoid regeneration
- **Batch Size**: Process dialogue in groups to balance memory/speed

## Error Handling

- Validate Fountain syntax, report line numbers
- Handle missing voice assignments gracefully
- Fallback to default voice if model unavailable
- Resume from cache if interrupted
- Clear error messages for audio device issues

## Testing Strategy

- Unit tests for parser with various Fountain examples
- Integration tests with small scripts
- Audio output validation (duration, format)
- Performance benchmarks
- Cross-platform compatibility (macOS, Linux, Windows)

## Open Questions

1. Should we support multiple TTS backends simultaneously?
2. How to handle very long dialogue (split into chunks)?
3. Should we add SSML-like markup for fine control?
4. What's the best approach for voice cloning (if needed)?
5. How to handle character voice consistency across sessions?

## Next Steps

1. Create detailed todo list
2. Set up project structure with directories
3. Add initial dependencies to `pyproject.toml`
4. Implement basic parser
5. Create proof-of-concept with Piper TTS
