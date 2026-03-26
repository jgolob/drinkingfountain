# Implementation Plan: Drinking Fountain

## Phase 1: Foundation & Project Setup

### Step 1.1: Initialize Project Structure
- [ ] Create directory structure under `src/drinkingfountain/`
- [ ] Create `__init__.py` files for all packages
- [ ] Set up test directory structure
- [ ] Create data directories (voices, outputs, cache) and add to `.gitignore`

### Step 1.2: Define Core Data Models
- [ ] `script.py`: Define `Script`, `Scene`, `Block` classes
  - `Block` types: `Dialogue`, `Action`, `SceneHeading`, `Character`, `Parenthetical`
  - Metadata: character names, scene locations, line numbers
- [ ] `config.py`: Define configuration dataclasses
  - `TTSConfig`, `AudioConfig`, `VoiceMapping`, `ProsodyRules`

### Step 1.3: Implement Fountain Parser
- [ ] `parser/fountain.py`: Line-by-line parser
  - Detect character lines (ALL CAPS, standalone)
  - Detect dialogue (following character)
  - Detect parentheticals (in parentheses)
  - Detect scene headings (INT./EXT., SCENE:)
  - Detect action blocks (everything else)
- [ ] Build script tree with proper hierarchy
- [ ] Handle edge cases: dual-dialogue, transitions, notes

### Step 1.4: Parser Tests
- [ ] Create test fixtures with sample Fountain scripts
- [ ] Test character extraction
- [ ] Test dialogue grouping
- [ ] Test scene detection
- [ ] Test parenthetical parsing
- [ ] Test error handling for malformed input

**Deliverable**: Working parser that can read a Fountain file and produce a structured script object.

---

## Phase 2: TTS Integration

### Step 2.1: Choose & Document TTS Backend
- [ ] Research Piper TTS installation options
  - Binary download vs pip package
  - Voice model download strategy
- [ ] Document voice model availability
  - English voices: en_US-amy, en_US-john, etc.
  - Other languages if needed
- [ ] Create voice model catalog/registry

### Step 2.2: Implement TTS Interface
- [ ] `tts/base.py`: Abstract base class `TTSBackend`
  - `generate(text: str, voice: str, **kwargs) -> AudioSegment`
  - `list_voices() -> List[Voice]`
  - `is_available() -> bool`
- [ ] `tts/piper.py`: Piper implementation
  - Handle binary invocation or Python wrapper
  - Parse Piper output to audio array
  - Support voice quality parameters
  - Error handling for missing models

### Step 2.3: Voice Management
- [ ] `voices/manager.py`: `VoiceManager` class
  - Load voice configuration from YAML
  - Auto-assign voices to characters
  - Validate voice availability
  - Provide fallback voice
- [ ] `voices/registry.py`: Registry of available voices
  - Scan installed voice models
  - Provide voice metadata (language, quality, sample)
  - Download/install voice models

### Step 2.4: TTS Caching
- [ ] `tts/cache.py`: `TTSCache` class
  - Generate cache key from text+voice+params
  - Store/retrieve cached audio files
  - Cache cleanup/limit policies
  - Optional: SQLite index for metadata

### Step 2.5: Prosody Detection & Adjustment
- [ ] Parse parentheticals for emotional cues
- [ ] Map cues to TTS parameters:
  - Speed adjustment
  - Pitch adjustment
  - Volume adjustment
- [ ] Apply adjustments in TTS generation

### Step 2.6: TTS Tests
- [ ] Mock TTS backend for unit tests
- [ ] Test voice assignment logic
- [ ] Test caching (hit/miss)
- [ ] Test prosody parameter mapping
- [ ] Integration test with real Piper (if available)

**Deliverable**: System that can generate individual audio segments for each dialogue line with appropriate voices.

---

## Phase 3: Audio Pipeline

### Step 3.1: Audio Format Abstraction
- [ ] `audio/formats.py`: Audio data structures
  - `AudioSegment` wrapper (pydub or numpy)
  - Format conversion utilities
  - Sample rate/channels normalization

### Step 3.2: Audio Mixing Engine
- [ ] `audio/mixer.py`: `AudioMixer` class
  - Add audio segments sequentially
  - Insert silence/pauses between segments
  - Handle overlapping (if needed for dual-dialogue)
  - Mix multiple tracks (speech + effects)

### Step 3.3: Timing & Pauses
- [ ] Implement configurable pause durations
  - Between dialogue lines
  - After scene headings
  - Between scenes
- [ ] Apply pauses during mixing
- [ ] Handle edge cases: end of script, consecutive scenes

### Step 3.4: Volume Normalization
- [ ] Analyze peak levels of all segments
- [ ] Apply gain to reach target level (-3dB)
- [ ] Prevent clipping
- [ ] Optional: LUFS normalization for broadcast standards

### Step 3.5: Sound Effects (Optional Phase 1)
- [ ] Define sound effect metadata format
- [ ] Load sound effect files
- [ ] Mix effects at specified points
- [ ] Volume envelope for effects

### Step 3.6: Output Rendering
- [ ] Export to WAV (default)
- [ ] Optional MP3 export (requires ffmpeg/lame)
- [ ] Set sample rate and channels
- [ ] Add metadata (title, script name, duration)

### Step 3.7: Audio Tests
- [ ] Test segment concatenation
- [ ] Test pause insertion
- [ ] Test normalization math
- [ ] Test format conversion
- [ ] Integration test: full script to audio

**Deliverable**: Complete audio pipeline that mixes all segments into final output file.

---

## Phase 4: CLI & Configuration

### Step 4.1: CLI Framework
- [ ] `cli.py`: Set up Click or argparse
- [ ] Main command: `drinkingfountain render <script>`
- [ ] Subcommands:
  - `voices list`
  - `voices download <voice>`
  - `voices test <voice> <text>`
- [ ] Argument parsing with validation
- [ ] Help text and examples

### Step 4.2: Configuration Management
- [ ] `config/settings.py`: `Config` class
  - Load from YAML file
  - Merge with defaults
  - Override with CLI flags
  - Validate configuration
- [ ] Config file locations and precedence
- [ ] Example config file template

### Step 4.3: Main Render Pipeline
- [ ] `cli.py`: Implement `render` command
  - Parse script file
  - Load configuration
  - Initialize voice manager
  - Generate TTS for all dialogue
  - Mix audio
  - Write output file
  - Show progress/progress bar
- [ ] Error handling and user feedback
- [ ] Performance timing and stats

### Step 4.4: Voice Commands
- [ ] `voices list`: Show available installed voices
- [ ] `voices download`: Download and install voice models
- [ ] `voices test`: Generate sample audio for voice preview
- [ ] `voices assign`: Interactive character-to-voice mapping

### Step 4.5: User Experience Polish
- [ ] Progress indicators for long operations
- [ ] Colored output for errors/warnings
- [ ] Verbose/debug logging option
- [ ] Dry-run mode (parse only, no generation)
- [ ] Stats reporting (duration, processing time, cache hits)

### Step 4.6: Documentation
- [ ] README.md with:
  - Project description
  - Installation instructions
  - Quick start guide
  - Configuration reference
  - Troubleshooting
- [ ] Example scripts in `examples/`
- [ ] Voice model download guide

### Step 4.7: CLI Tests
- [ ] Test command parsing
- [ ] Test config loading/validation
- [ ] Test end-to-end render with small script
- [ ] Test error paths (missing file, bad config)

**Deliverable**: Complete command-line tool with all features integrated.

---

## Phase 5: Packaging & Distribution

### Step 5.1: pyproject.toml Finalization
- [ ] Add all runtime dependencies
  - `pydub`, `numpy`, `click`, `pyyaml`
  - Piper TTS dependency (package or binary)
- [ ] Add optional dependencies (ffmpeg for mp3)
- [ ] Configure entry points: `drinkingfountain = "drinkingfountain.cli:main"`
- [ ] Add build system (hatchling, setuptools, etc.)

### Step 5.2: uv Integration
- [ ] Test `uv sync` installs all dependencies
- [ ] Test `uv run drinkingfountain` works
- [ ] Document uv usage in README

### Step 5.3: Distribution Prep
- [ ] Build package: `uv build`
- [ ] Test install from dist: `uv pip install dist/*.whl`
- [ ] Verify CLI entry point works after install
- [ ] Create Homebrew formula (optional)
- [ ] Create PyPI package (optional)

### Step 5.4: Voice Model Distribution
- [ ] Document voice model download process
- [ ] Create script to download default voices
- [ ] Consider bundling minimal voice set
- [ ] Document voice licensing

---

## Future Enhancements (Post-MVP)

### Enhancement 1: Advanced Voice Features
- Voice cloning with speaker embeddings
- Voice style transfer
- Emotional voice presets
- Custom voice training

### Enhancement 2: Audio Effects
- Ambient soundscapes per scene
- Reverb for different locations
- Foley sound effects library
- Music background tracks

### Enhancement 3: Script Editing
- Interactive voice assignment UI
- Script validation and linting
- Character consistency checking
- Dialogue timing adjustment

### Enhancement 4: Performance
- Parallel TTS generation
- GPU acceleration support
- Streaming generation for long scripts
- Incremental rendering (cache reuse)

### Enhancement 5: Developer Experience
- VS Code extension
- Live preview with audio waveform
- Script diff with audio changes
- API for programmatic use

---

## Testing Checklist

### Unit Tests
- [ ] Parser: all block types
- [ ] Voice manager: assignment, fallback
- [ ] TTS cache: key generation, storage
- [ ] Audio mixer: concatenation, pauses
- [ ] Config: loading, validation, defaults

### Integration Tests
- [ ] Full pipeline: script → audio
- [ ] Voice assignment with config override
- [ ] Cache hit/miss scenarios
- [ ] Error recovery (missing voice, bad script)

### Manual Testing
- [ ] Sample script rendering
- [ ] Different voice qualities
- [ ] Long script (>1000 lines)
- [ ] Various pause configurations
- [ ] MP3 export
- [ ] Cross-platform (macOS, Linux, Windows)

---

## Milestone Definitions

**M1 (Parser Complete)**: Can parse any Fountain script and extract all dialogue with correct character assignments.

**M2 (TTS Working)**: Can generate audio for a single dialogue line with a specified voice.

**M3 (Pipeline Complete)**: Can convert a complete script to audio with automatic voice assignment.

**M4 (CLI Ready)**: Full command-line interface with all features, ready for beta testing.

**M5 (Release Candidate)**: All tests passing, documentation complete, packaged and distributable.

---

## Risk Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Piper TTS not installable on all platforms | High | Medium | Provide alternative backends (Coqui, Transformers) |
| Voice model downloads too large | Medium | Low | Provide minimal voice set, lazy download |
| Audio quality poor/unnatural | High | Medium | Offer multiple voice options, quality settings |
| Performance too slow for long scripts | Medium | Medium | Caching, batch processing, progress feedback |
| Fountain format variations break parser | Medium | Medium | Comprehensive test suite, parser flexibility |

---

## Success Criteria

1. Can render a 10-page script (≈100 lines dialogue) in <10 minutes on modern laptop
2. Audio quality is intelligible and suitable for table reads
3. Voice assignments are consistent and configurable
4. CLI is intuitive and well-documented
5. All tests pass on macOS, Linux, and Windows
6. Zero external API dependencies (fully local)
