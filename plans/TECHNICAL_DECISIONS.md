# Technical Decisions & Research

## 1. TTS Backend Selection

### Why Piper TTS?

After evaluating options, **Piper TTS** is the recommended choice for the following reasons:

| Criterion | Piper TTS | Coqui TTS | HuggingFace Transformers |
|-----------|-----------|-----------|-------------------------|
| **Model Size** | ~50MB per voice | 200MB-2GB | 300MB-1GB |
| **Speed** | Very fast (2-5x RT) | Slow (0.5-2x RT) | Medium (1-3x RT) |
| **Quality** | Good (neural) | Excellent | Good-Very Good |
| **Dependencies** | Minimal (C++ binary) | Heavy (PyTorch) | Moderate (transformers) |
| **CPU Usage** | Low | High | Medium |
| **Voice Count** | 50+ voices | Unlimited (training) | Model-dependent |
| **Installation** | Download binary + models | pip install | pip install |
| **Python API** | Limited (subprocess) | Full Python | Full Python |
| **Voice Cloning** | No | Yes | Limited |

**Decision**: Piper provides the best balance of speed, quality, and simplicity for a table read tool. The small model size and fast inference make it practical for batch processing entire scripts without requiring a GPU.

### Piper TTS Implementation Details

**Installation**:
```bash
# Download Piper binary (platform-specific)
# Place in ~/.local/bin/piper or project bin/

# Download voice models
# Voices: https://huggingface.co/rhasspy/piper-voices/tree/main
# Structure: {language}-{name}-{quality}.onnx
# Example: en_US-amy-medium.onnx
```

**Usage**:
```bash
echo "Hello world" | piper --model en_US-amy-medium.onnx --output_file output.wav
```

**Python Integration**:
```python
import subprocess
import tempfile

def generate_piper(text: str, model_path: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        proc = subprocess.run(
            ['piper', '--model', model_path, '--output_file', f.name],
            input=text.encode('utf-8'),
            capture_output=True
        )
        proc.check_returncode()
        return f.read()
```

**Alternative**: If a pure Python package becomes available, we'll switch to it for better integration.

---

## 2. Fountain Format Specification

### Fountain Syntax Summary

Fountain is a plain-text format for screenplays with these key conventions:

**Scene Headings**:
```
INT. HOUSE - DAY
EXT. PARK - NIGHT
SCENE 1: THE BEGINNING
```
- Typically start with `INT.` or `EXT.` (case-insensitive)
- May include location and time (DAY/NIGHT)
- Sometimes prefixed with `SCENE:` or just numbered

**Character Names**:
```
JOHN
(angrily)
Hello, Mary.
```
- ALL CAPS on their own line
- May be followed by parenthetical on next line
- Dialogue follows on subsequent lines

**Dialogue**:
```
Hello, Mary.
How are you?
```
- Lines after a character, not indented or slightly indented
- Multiple paragraphs allowed
- May include parentheticals inline

**Parentheticals**:
```
(angrily)
(whispering)
(to John)
```
- Wrapped in parentheses
- On their own line, between character and dialogue or within dialogue
- Indicated delivery, emotion, or target

**Action**:
```
John enters the room.
He looks around nervously.
```
- Any text that's not a recognized block type
- Can be multiple lines
- Usually present tense, descriptive

**Transitions**:
```
CUT TO:
FADE OUT.
```
- Often ALL CAPS, right-aligned in proper screenplays
- In Fountain, just ALL CAPS on their own line

**Dual Dialogue**:
```
JOHN
                     MARY
Hello.               Hi!
```
- Two characters speaking simultaneously
- Indicated by side-by-side formatting
- Advanced feature, may skip for MVP

### Parsing Strategy

**State Machine Approach**:
```
State: LookingForBlock
  ├─ Line is empty → stay in LookingForBlock
  ├─ Line matches SCENE pattern → create SceneHeading, switch to InScene
  ├─ Line is ALL CAPS (and not dialogue continuation) → create Character
  └─ Otherwise → create Action

State: InScene
  ├─ Line is empty → stay in InScene
  ├─ Line is ALL CAPS → create Character, switch to AfterCharacter
  └─ Otherwise → add Action to current scene

State: AfterCharacter
  ├─ Line is empty → stay in AfterCharacter
  ├─ Line is (parenthetical) → create Parenthetical
  ├─ Line is ALL CAPS (new character) → create Character
  └─ Otherwise (dialogue) → create Dialogue, switch to InDialogue

State: InDialogue
  ├─ Line is empty → switch to LookingForBlock (dialogue ended)
  ├─ Line is (parenthetical) → create Parenthetical
  ├─ Line is ALL CAPS (new character) → create Character, switch to AfterCharacter
  └─ Otherwise (continuation) → append to current dialogue
```

**Block Types**:
```python
@dataclass
class Block:
    type: BlockType
    line_number: int
    content: str

@dataclass
class Character(Block):
    name: str

@dataclass
class Parenthetical(Block):
    text: str

@dataclass
class Dialogue(Block):
    character: str
    parentheticals: List[Parenthetical]

@dataclass
class SceneHeading(Block):
    location: str
    time: Optional[str]  # DAY/NIGHT

@dataclass
class Action(Block):
    pass

@dataclass
class Transition(Block):
    pass
```

**Edge Cases**:
- Empty lines separate blocks but may be preserved for spacing
- Indentation: ignore for parsing, use only content patterns
- Continuation lines: dialogue can span multiple lines
- Nested parentheticals: rare, but possible (handle gracefully)
- Character name variations: "JOHN" vs "JOHN (O.S.)" - strip parenthetical part
- Notes in brackets: `[note]` - usually ignored or treated as action

---

## 3. Audio Processing with PyDub

### Why PyDub?

PyDub provides a high-level, intuitive API for audio manipulation:
- Simple concatenation: `audio = seg1 + seg2 + seg3`
- Built-in silence generation: `AudioSegment.silent(duration=300)`
- Easy format conversion: `audio.export("output.mp3", format="mp3")`
- Volume normalization: `audio.apply_gain(target_dBFS - audio.dBFS)`
- Compatible with ffmpeg for wide format support

### Installation

```bash
pip install pydub
# Also install ffmpeg system package for MP3 support
# macOS: brew install ffmpeg
# Ubuntu: apt-get install ffmpeg
# Windows: download from ffmpeg.org
```

### Audio Pipeline Example

```python
from pydub import AudioSegment

def mix_script_audio(segments: List[Tuple[AudioSegment, float]]) -> AudioSegment:
    """
    segments: list of (audio, timestamp) tuples
    Returns mixed audio at 44.1kHz, stereo
    """
    # Determine total duration
    total_duration = max(ts + len(audio) for audio, ts in segments)

    # Create silent base track
    output = AudioSegment.silent(
        duration=total_duration,
        frame_rate=44100
    )

    # Overlay each segment at its timestamp
    for audio, timestamp in segments:
        output = output.overlay(audio, position=timestamp)

    return output
```

### Normalization

```python
def normalize_audio(audio: AudioSegment, target_dBFS: float = -3.0) -> AudioSegment:
    """Normalize audio to target peak level"""
    current_dBFS = audio.dBFS
    gain = target_dBFS - current_dBFS
    return audio.apply_gain(gain)
```

**Note**: dBFS in PyDub is average RMS, not true peak. For peak normalization:
```python
def normalize_peak(audio: AudioSegment, target_dBFS: float = -3.0) -> AudioSegment:
    """Normalize to peak level"""
    peak = audio.max_dBFS
    gain = target_dBFS - peak
    return audio.apply_gain(gain)
```

---

## 4. Configuration Management

### YAML Configuration

**File Locations** (searched in order):
1. Path from `--config` flag
2. `./drinkingfountain.yaml` (current directory)
3. `~/.config/drinkingfountain/config.yaml` (user config)

**Schema**:
```yaml
# TTS backend selection
backend: piper  # or "coqui", "transformers"

# Piper-specific
piper:
  binary_path: ~/.local/bin/piper  # auto-detect if not set
  voice_dir: ~/.local/share/piper/voices  # auto-detect if not set
  default_quality: medium  # x-low, low, medium, high, x-high

# Audio settings
audio:
  sample_rate: 22050  # 22050 or 44100
  channels: mono  # mono or stereo
  normalize: true
  target_level: -3.0  # dBFS

# Timing (seconds)
timing:
  pause_between_lines: 0.3
  pause_after_scene_heading: 1.0
  pause_between_scenes: 2.0
  pause_after_action: 0.5  # optional

# Voice assignments
voices:
  # Character name -> voice ID
  NARRATOR: en_US-amy-medium
  JOHN: en_US-john-medium
  MARY: en_US-mary-medium

# Prosody adjustments (parenthetical -> params)
prosody:
  angrily:
    speed: 1.1
    pitch: 1.1
  sadly:
    speed: 0.9
    pitch: 0.9
  whispering:
    volume: 0.8
  excited:
    speed: 1.15
    pitch: 1.05
  nervous:
    speed: 1.2
    pitch: 1.1

# Output
output:
  format: wav  # wav or mp3
  directory: ./outputs
```

### Python Config Class

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import yaml

@dataclass
class ProsodyConfig:
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0

@dataclass
class AudioConfig:
    sample_rate: int = 22050
    channels: str = "mono"
    normalize: bool = True
    target_level: float = -3.0

@dataclass
class TimingConfig:
    pause_between_lines: float = 0.3
    pause_after_scene_heading: float = 1.0
    pause_between_scenes: float = 2.0

@dataclass
class Config:
    backend: str = "piper"
    audio: AudioConfig = field(default_factory=AudioConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    voices: Dict[str, str] = field(default_factory=dict)
    prosody: Dict[str, ProsodyConfig] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        # Search for config file
        config_path = path or cls.find_config()
        if config_path and config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f)
            return cls.from_dict(data)
        return cls()  # defaults

    @classmethod
    def find_config(cls) -> Optional[Path]:
        # Check current dir, then user config dir
        candidates = [
            Path.cwd() / "drinkingfountain.yaml",
            Path.home() / ".config" / "drinkingfountain" / "config.yaml"
        ]
        for path in candidates:
            if path.exists():
                return path
        return None
```

---

## 5. Caching Strategy

### Cache Key Generation

```python
import hashlib

def generate_cache_key(
    text: str,
    voice_id: str,
    speed: float = 1.0,
    pitch: float = 1.0,
    volume: float = 1.0
) -> str:
    """Generate deterministic cache key from TTS parameters"""
    key_string = f"{text}|{voice_id}|{speed:.2f}|{pitch:.2f}|{volume:.2f}"
    return hashlib.sha256(key_string.encode('utf-8')).hexdigest()[:16]
```

### Cache Storage

```
cache/
├── index.db  # SQLite: key -> metadata (text, voice, params, timestamp, duration)
└── audio/
    ├── abc123def456.wav
    ├── ghi789jkl012.wav
    └── ...
```

**Cache Policy**:
- No expiration (cache is valid indefinitely)
- Manual cleanup with `drinkingfountain cache clear`
- Size limit: 1000 entries or 10GB (configurable)
- LRU eviction when limit reached

### Cache Implementation

```python
import sqlite3
from pathlib import Path

class TTSCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.audio_dir = cache_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = cache_dir / "index.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    text TEXT,
                    voice_id TEXT,
                    speed REAL,
                    pitch REAL,
                    volume REAL,
                    audio_path TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    duration_ms INTEGER
                )
            """)

    def get(self, key: str) -> Optional[bytes]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT audio_path FROM cache WHERE key = ?",
                (key,)
            ).fetchone()
            if row:
                audio_path = Path(row[0])
                if audio_path.exists():
                    return audio_path.read_bytes()
        return None

    def put(self, key: str, audio_data: bytes, metadata: dict):
        audio_path = self.audio_dir / f"{key}.wav"
        audio_path.write_bytes(audio_data)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache
                (key, text, voice_id, speed, pitch, volume, audio_path, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key,
                metadata["text"],
                metadata["voice_id"],
                metadata.get("speed", 1.0),
                metadata.get("pitch", 1.0),
                metadata.get("volume", 1.0),
                str(audio_path),
                metadata.get("duration_ms", 0)
            ))
```

---

## 6. Prosody from Parentheticals

### Parenthetical Detection

Parentheticals appear in two contexts:
1. After character name, before dialogue: indicates delivery
   ```
   JOHN
   (angrily)
   Get out of here!
   ```
2. Within dialogue: indicates aside or emotion mid-line
   ```
   JOHN
   I can't believe you said that (laughing).
   ```

**Parsing**:
- Parenthetical lines: `^\([^)]+\)$` (entire line in parentheses)
- Inline parentheticals: `\([^)]+\)` within dialogue line
- Extract text inside parentheses, strip whitespace

### Prosody Mapping

**Default Mapping**:
| Parenthetical | Speed | Pitch | Volume | Notes |
|---------------|-------|-------|--------|-------|
| angrily | 1.1 | 1.1 | 1.0 | |
| sad | 0.9 | 0.9 | 1.0 | |
| whispering | 1.0 | 1.0 | 0.6 | |
| shouting | 1.0 | 1.0 | 1.3 | |
| excited | 1.15 | 1.05 | 1.0 | |
| nervous | 1.2 | 1.1 | 1.0 | |
| slow | 0.8 | 1.0 | 1.0 | |
| fast | 1.2 | 1.0 | 1.0 | |
| sarcastic | 1.0 | 0.95 | 1.0 | Monotone drop |

**Implementation**:
```python
PROSODY_MAP = {
    "angry": {"speed": 1.1, "pitch": 1.1},
    "sad": {"speed": 0.9, "pitch": 0.9},
    # ...
}

def parse_parentheticals(dialogue_block: Dialogue) -> List[ProsodyEvent]:
    """Extract prosody changes from dialogue block"""
    events = []
    for parenthetical in dialogue_block.parentheticals:
        text = parenthetical.text.lower()
        for cue, params in PROSODY_MAP.items():
            if cue in text:
                events.append(ProsodyEvent(
                    params.speed,
                    params.pitch,
                    params.volume
                ))
    return events
```

**Note**: Piper TTS doesn't directly support speed/pitch parameters via command line in all versions. May need to:
- Use SSML if supported (unlikely)
- Pre-process text with punctuation for pacing
- Post-process audio for speed (time-stretching)
- Accept limited prosody control in MVP

---

## 7. Performance Optimization

### Batch Processing

Instead of generating each line individually:
1. Collect all dialogue lines for a given voice
2. Generate in a single Piper invocation (if supported)
3. Split output into segments

**Piper Limitation**: Piper processes one text at a time. Workaround:
- Keep model loaded in memory (if using Python API)
- Or batch via multiple subprocess calls with same model (model load overhead)

**Optimization**:
```python
# If Piper had Python API:
model = piper.PiperModel(voice_model_path)
for line in lines:
    audio = model.synthesize(line)
    # ...

# With subprocess, minimize calls:
# - Group by voice (load model once per voice)
# - Use piper's --output_raw for streaming
```

### Parallel Generation

```python
from concurrent.futures import ProcessPoolExecutor

def generate_parallel(dialogue_blocks: List[Dialogue], max_workers: int = 4):
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(tts.generate, block): block
            for block in dialogue_blocks
        }
        results = {}
        for future in as_completed(futures):
            block = futures[future]
            results[block] = future.result()
    return results
```

**Caveat**: Piper model loading is expensive (~1-2s). Parallel only helps if:
- Many independent lines (>50)
- Enough CPU cores
- Sufficient RAM for multiple model instances

**Recommendation**: For MVP, sequential generation is fine. Add parallel later if needed.

### Caching Impact

- First run: full generation time (slow)
- Subsequent runs: only uncached lines (fast)
- Cache hit rate typically >90% for iterative development

---

## 8. Error Handling & Validation

### Script Validation

```python
class ScriptValidator:
    def validate(self, script: Script) -> List[ValidationError]:
        errors = []

        # Check for dialogue without character
        for block in script.blocks:
            if isinstance(block, Dialogue) and not block.character:
                errors.append(ValidationError(
                    f"Line {block.line_number}: Dialogue without character"
                ))

        # Check for character without dialogue
        characters_without_dialogue = script.characters - script.characters_with_dialogue
        for char in characters_without_dialogue:
            errors.append(ValidationWarning(
                f"Character '{char}' has no dialogue"
            ))

        # Check for very long dialogue lines (>500 chars)
        for block in script.blocks:
            if isinstance(block, Dialogue) and len(block.content) > 500:
                errors.append(ValidationWarning(
                    f"Line {block.line_number}: Very long dialogue ({len(block.content)} chars)"
                ))

        return errors
```

### TTS Error Recovery

- **Missing voice model**: Fall back to default voice, log warning
- **Piper binary not found**: Clear error with install instructions
- **Generation failure**: Retry once, then skip with error log
- **Out of memory**: Reduce batch size, use lower quality

### Audio Mixing Errors

- **Sample rate mismatch**: Resample all to common rate
- **Channel mismatch**: Convert all to mono or stereo
- **Clipping**: Auto-reduce gain if normalization fails

---

## 9. Testing Strategy Details

### Test Fixtures

Create `tests/fixtures/`:
- `simple.fountain`: 2 characters, 3 scenes, basic dialogue
- `complex.fountain`: 5+ characters, parentheticals, dual dialogue attempt
- `edge_cases.fountain`: empty lines, long dialogue, special chars
- `malformed.fountain`: missing character, orphaned dialogue

### Mocking TTS

```python
class MockTTSBackend(TTSBackend):
    def __init__(self):
        self.generated = []

    def generate(self, text: str, voice: str, **kwargs) -> AudioSegment:
        # Generate silent audio of length proportional to text
        duration_ms = len(text) * 30  # ~30ms per char
        self.generated.append((text, voice, kwargs))
        return AudioSegment.silent(duration=duration_ms)

    def list_voices(self) -> List[Voice]:
        return [Voice("test_voice", "Test Voice", "en")]
```

### Integration Test Example

```python
def test_full_pipeline():
    # Arrange
    script = FountainParser.parse("tests/fixtures/simple.fountain")
    config = Config(voices={"NARRATOR": "test_voice", "JOHN": "test_voice"})
    tts = MockTTSBackend()
    mixer = AudioMixer(config.audio)

    # Act
    audio = render_script(script, config, tts, mixer)

    # Assert
    assert audio.duration_seconds > 0
    assert len(tts.generated) > 0
    assert audio.frame_rate == config.audio.sample_rate
```

---

## 10. Dependencies Summary

### Core Dependencies (pyproject.toml)

```toml
[project]
dependencies = [
    "pydub>=0.25.1",
    "numpy>=1.24.0",
    "pyyaml>=6.0",
    "click>=8.1.0",
    "soundfile>=0.12.0; platform_system != 'Windows'",
    "soundfile>=0.12.1; platform_system == 'Windows'",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "pytest-mock>=3.10",
    "black>=23.0",
    "ruff>=0.0.290",
    "mypy>=1.0",
]

# Piper TTS: binary distribution, not pip package
# Document manual installation
```

### System Dependencies

- **ffmpeg**: For MP3 export and audio codec support
  - macOS: `brew install ffmpeg`
  - Ubuntu: `apt-get install ffmpeg`
  - Windows: Download from ffmpeg.org

- **Piper TTS binary**: Download from GitHub releases
  - Not a pip package (yet)
  - Place in PATH or config-specified location

---

## 11. Alternative Approaches Considered

### Why Not Coqui TTS?

**Pros**:
- Higher quality, more natural
- Voice cloning possible
- Pure Python API

**Cons**:
- Heavy PyTorch dependency (~2GB)
- Slow inference without GPU
- Complex setup
- Overkill for table reads

**Verdict**: Could be a Phase 2 enhancement if quality is insufficient.

### Why Not Edge-TTS (Microsoft)?

**Pros**:
- Very high quality
- Many voices
- Simple Python API

**Cons**:
- Requires Windows or WSL
- Cloud API (not local)
- Rate limits, privacy concerns

**Verdict**: Violates "local only" requirement.

### Why Not eSpeak NG?

**Pros**:
- Extremely lightweight
- Works everywhere
- Offline

**Cons**:
- Robotic, unnatural sound
- Limited voice variety
- Poor prosody

**Verdict**: Quality too low for table reads.

---

## 12. Open Issues & Questions

1. **Long dialogue handling**: Piper has text length limits (~500 chars). Need chunking strategy.
   - Solution: Split on sentence boundaries, add pauses between chunks.

2. **Voice model storage**: Where to store downloaded voices?
   - Proposal: `~/.local/share/drinkingfountain/voices/` (cross-platform via `appdirs`)

3. **SSML support**: Piper doesn't support SSML. How to control prosody?
   - Solution: Use command-line parameters if available, or accept basic control.

4. **Dual dialogue**: How to handle simultaneous speech?
   - MVP: Ignore, treat as sequential
   - Future: Mix overlapping segments

5. **Character voice consistency**: If auto-assigning, how to keep same voice across multiple scripts?
   - Solution: Global voice mapping config that persists across runs.

6. **Testing audio output**: How to assert audio quality in automated tests?
   - Solution: Test duration, sample rate, RMS level. Not subjective quality.

7. **Cross-platform binary**: Piper needs different binaries for different OSes.
   - Solution: Document platform-specific downloads, or bundle in package.

---

## 13. Research Resources

### Piper TTS
- GitHub: https://github.com/rhasspy/piper
- Voices: https://huggingface.co/rhasspy/piper-voices
- Demo: https://huggingface.co/spaces/rhasspy/piper-tts

### Fountain Format
- Official site: http://fountain.io/
- Syntax spec: https://github.com/scriptfountain/fountain-syntax
- Parser reference: https://github.com/mattdmo/parse-fountain

### PyDub
- Docs: https://github.com/jiaaro/pydub
- Installation: https://github.com/jiaaro/pydub#installation

### Audio Normalization
- LUFS vs Peak: https://podcasters.spotify.com/learn/audio-normalization-lufs-vs-peak
- PyDub gain: https://github.com/jiaaro/pydub#audiosegmentapply_gain

---

## 14. Implementation Order (Prioritized)

1. **Parser** (no external deps) - can start immediately
2. **Data models** - support parser and TTS
3. **TTS interface** - abstract, then Piper implementation
4. **Voice manager** - tie parser output to TTS
5. **Audio mixing** - combine segments
6. **CLI** - glue everything together
7. **Config** - make it flexible
8. **Caching** - speed up iteration
9. **Prosody** - enhance expressiveness
10. **Polish** - docs, tests, packaging

**Parallel work**:
- Parser and data models can be done together
- TTS interface and voice manager are coupled
- Audio mixing independent of TTS backend
- CLI comes last once core pipeline works

---

## 15. Success Metrics

- **Parser accuracy**: 100% on valid Fountain, clear errors on invalid
- **Generation speed**: >2x real-time on modern laptop CPU
- **Audio quality**: Intelligible, consistent voices, no glitches
- **Cache hit rate**: >90% on repeated runs with same script
- **Test coverage**: >80% of code paths
- **User experience**: One command from script to audio, <5 min setup
