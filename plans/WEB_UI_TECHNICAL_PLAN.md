# Web UI Technical Plan for DrinkingFountain

**Date**: 2025-03-30
**Last refined**: 2026-05-27
**Status**: In progress on `webui`
**Objective**: Add a web-based UI that accepts Fountain scripts and produces audio plays/virtual table reads

---

## 1. Executive Summary

This plan outlines the addition of a lightweight web interface to DrinkingFountain, enabling users to upload or paste Fountain scripts and receive generated audio through their browser. The implementation will reuse existing core services (`RenderService`, `VoiceService`, `FountainParser`, `AudioMixer`) with minimal modifications, wrapping them in a Flask-based web layer.

### Current Branch Status

The branch now contains the MVP backend and browser UI skeleton:

- `Config.from_dict()` is available for programmatic configuration.
- `FountainParser.parse_string()` shares the parser state machine with file parsing.
- `RenderService.render_from_string()` and optional `TimingBlock` collection are implemented.
- Flask app factory, routes, render store, health/voices APIs, synchronized playback UI, and `drinkingfountain-web` entry point are in place.
- Automated coverage now includes web form config, render store cleanup, render response URLs, temp cleanup on early voice failures, and parser string reuse behavior.

Remaining work should focus on hardening and polish rather than basic scaffolding: replace CDN assets for offline/local reliability, improve frontend validation and accessibility states, manually verify the UI with installed Piper voices, and decide whether render timeout/cancellation should become a background job model for longer scripts.

**Key Benefits**:
- Lower barrier to entry for non-CLI users
- Easy sharing and collaboration via web interface
- Potential for future enhancements (real-time progress, preview, collaboration)
- Maintains all existing functionality and code quality

---

## 2. Recommended Web Framework: Flask

### Justification

| Criteria | Flask | FastAPI | Streamlit |
|----------|-------|---------|-----------|
| **Learning curve** | Low | Medium | Very Low |
| **Control over responses** | Excellent | Excellent | Limited |
| **File upload/download** | Excellent | Excellent | Good |
| **Async support** | Limited (WSGI) | Excellent (ASGI) | Built-in |
| **Dependencies** | Minimal | Moderate | Heavy |
| **Custom UI flexibility** | Full control | Full control | Template-limited |
| **Suitability for CPU-bound tasks** | Good (threaded) | Good (async) | Good |
| **Integration with existing sync code** | Seamless | Seamless | Possible but awkward |

**Why Flask is optimal**:
1. **Simplicity**: Flask's minimalism matches DrinkingFountain's philosophy. No complex async/await patterns needed for CPU-bound TTS work.
2. **Mature file handling**: `send_file` and file uploads are straightforward and well-documented.
3. **Thread-safe per-request isolation**: Each request can create its own service instances, avoiding concurrency issues.
4. **Minimal new dependencies**: Only `Flask` and `Werkzeug` (already included via Flask).
5. **Easy to deploy**: Works with standard WSGI servers (Gunicorn, uWSGI) for production.
6. **Template flexibility**: Full HTML/CSS/JS control for a custom UI.

**Alternatives considered**:
- **FastAPI**: Excellent but async features not needed; slightly more boilerplate for simple file responses.
- **Streamlit**: Fast to prototype but less control over layout and file handling; would require rethinking as a "data app" rather than a traditional web app.
- **Django**: Overkill; too much infrastructure for a single-purpose tool.

---

## 3. Architecture Overview

### 3.1 High-Level Design

```
┌─────────────────┐
│   Web Browser   │
└────────┬────────┘
         │ HTTP (multipart/form-data, GET/POST)
         ▼
┌─────────────────────────────────────────────┐
│              Flask Web Layer                │
│  ┌─────────────────────────────────────┐  │
│  │  Routes & Controllers (app.py)      │  │
│  │  - GET /            → UI page        │  │
│  │  - POST /render     → process script │  │
│  │  - GET /api/voices → list voices    │  │
│  └─────────────────────────────────────┘  │
│         │                                  │
│         │ Creates per-request instances   │
│         ▼                                  │
│  ┌─────────────────────────────────────┐  │
│  │  Service Factory                   │  │
│  │  - Config (from defaults + form)   │  │
│  │  - TTS backend (Piper + cache)     │  │
│  │  - VoiceManager                    │  │
│  │  - RenderService                   │  │
│  └─────────────────────────────────────┘  │
│         │                                  │
│         │ render(script, output=temp)     │
│         ▼                                  │
│  ┌─────────────────────────────────────┐  │
│  │  Core Services (existing code)     │  │
│  │  - RenderService                   │  │
│  │  - FountainParser                  │  │
│  │  - AudioMixer                      │  │
│  │  - PiperTTSBackend                 │  │
│  └─────────────────────────────────────┘  │
│         │                                  │
│         │ Returns RenderResult            │
│         ▼                                  │
│  ┌─────────────────────────────────────┐  │
│  │  Response Builder                  │  │
│  │  - Set headers (Content-Type)      │  │
│  │  - Stream file or send directly    │  │
│  └─────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
         │
         │ Audio file (WAV/MP3)
         ▼
┌─────────────────┐
│   Web Browser   │
│  (download/play)│
└─────────────────┘
```

### 3.2 Integration Strategy

**Key principle**: The web layer is a thin wrapper. All business logic remains in `services.py`, `parser/`, `audio/`, `tts/`, etc.

**Per-request service initialization**:
```python
# In Flask route
def render_endpoint():
    # 1. Parse form data (script, config options)
    # 2. Build Config object programmatically (no file needed)
    # 3. Create TTS backend (PiperTTSBackend)
    # 4. Wrap with CachedTTSBackend (optional, can use temp cache dir)
    # 5. Create VoiceManager(tts)
    # 6. Apply voice overrides from form
    # 7. Create RenderService(config, tts, voice_mgr, narrator_cfg)
    # 8. Render to temporary file
    # 9. Return send_file(temp_path)
    # 10. Cleanup temp file after response
```

**Why per-request (not global) instances?**
- Thread safety: No shared mutable state between requests
- Simplicity: No need for locks or async coordination
- Isolation: Each render gets fresh voice caches, consistent assignments
- Acceptable performance: Service initialization is cheap compared to TTS synthesis

**Temporary file management**:
- Use `tempfile.NamedTemporaryFile(delete=False)` or `tempfile.mkdtemp()`
- Cleanup via Flask `@app.after_request` or `try/finally`
- Store temp paths in request context or use context manager

---

## 4. Key Endpoints and Pages

### 4.1 UI Page: `GET /`

**Purpose**: Main interface for script input and configuration.

**Features**:
- Textarea for pasting Fountain script
- File upload input for `.fountain` files
- Configuration form sections:
  - **Audio**: Sample rate (22050, 44100), Channels (mono/stereo), Normalization toggle, Target level
  - **Timing**: Pauses between lines, after scene heading, between scenes
  - **Narrator**: Enable/disable, voice selection (dropdown), expand INT/EXT toggle, narrative pauses
  - **Voices**: Character-to-voice mapping (dynamic table: add/remove rows for character name + voice ID)
  - **Output format**: WAV or MP3 (if ffmpeg available)
- Submit button: "Render Audio"
- Optional: List available voices (fetch from `/api/voices` on page load)

**UI/UX considerations**:
- Simple, clean design (Bootstrap or Tailwind CSS via CDN)
- Client-side validation (required script field)
- Progress indicator (since rendering can take 10s- minutes)
- Error display (inline or modal)

### 4.2 Render Endpoint: `POST /render`

**Purpose**: Accept script, generate audio and timing track, return render ID.

**Request**:
- `Content-Type`: `multipart/form-data`
- Fields:
  - `script` (text area or file upload) – at least one required
  - `output_format` (select: `wav`, `mp3`) – default `wav`
  - Audio/timing/narrator/voice config fields (matching Config dataclass fields)
  - `include_timing` (checkbox) – generate timing track for synced playback (default: true)
- Optional: `voice_override_{character}` for dynamic character mapping (or use JSON field)

**Response**:
- Success (200): JSON object:
  ```json
  {
    "status": "complete",
    "render_id": "abc123xyz",
    "audio_url": "/audio/abc123xyz.wav",
    "timing_url": "/timing/abc123xyz.json",
    "duration": 125.4,
    "script_title": "My Script"
  }
  ```
- Error (400/500): JSON with `{"error": "description"}`

**Behavior**:
- Validate input (script not empty, valid config values)
- Create `Config` object from form data (use defaults for missing fields)
- Initialize services
- Render to temporary WAV file
- If `include_timing` is true:
  - Generate timing track (list of blocks with start/end times)
  - Save timing JSON to a separate temp file
  - Store mapping of `render_id` → (audio_path, timing_path) in server-side store
- If MP3 requested: convert audio to MP3 (timing track unchanged)
- Return JSON with URLs; cleanup will happen later (see cleanup strategy)

**Streaming vs. complete file**:
- Render complete audio file first (required for WAV header and MP3 conversion)
- Audio is served via a separate static endpoint (`/audio/<render_id>`)
- This allows the frontend to set up an audio player and fetch timing data independently

### 4.3 Audio Streaming Endpoint: `GET /audio/<render_id>`

**Purpose**: Serve the generated audio file for in-browser playback.

**Response**:
- `Content-Type: audio/wav` or `audio/mpeg` (depending on requested format)
- `Content-Disposition: inline` (suggest browser play in-place)
- Body: binary audio file

**Implementation**:
- Look up `render_id` in server-side store (dict mapping to audio path)
- If found and file exists, `send_file(audio_path)`
- If not found or expired, return 404

---

### 4.4 Timing Track Endpoint: `GET /timing/<render_id>`

**Purpose**: Serve the timing JSON for synchronized script display.

**Response**:
- `Content-Type: application/json`
- Body: timing data

**Timing JSON format**:
```json
{
  "title": "Script Title",
  "duration": 125.4,
  "blocks": [
    {
      "type": "scene_heading",
      "text": "INT. COFFEE SHOP - DAY",
      "start": 0.0,
      "end": 2.5
    },
    {
      "type": "dialogue",
      "character": "JOHN",
      "text": "This is pretty good.",
      "start": 2.8,
      "end": 5.2
    },
    {
      "type": "action",
      "text": "Sarah enters, carrying a stack of books.",
      "start": 5.5,
      "end": 8.1
    }
  ]
}
```

**Implementation**:
- Look up `render_id`, return timing JSON
- Could also embed timing in the HTML page initially, but separate URL allows reuse

---

### 4.5 API Endpoint: `GET /api/voices`

**Purpose**: List available voice models for frontend dropdowns.

**Response** (JSON):
```json
{
  "voices": ["en_US-amy-medium", "en_US-john-high", ...],
  "narrator_suggestion": "en_US-amy-medium"  // optional: recommended narrator
}
```

**Optional**: Could also list voice metadata (language, quality) if needed.

### 4.6 Health Check: `GET /api/health`

**Purpose**: Verify service is running and Piper TTS is available.

**Response** (JSON):
```json
{
  "status": "healthy",
  "piper_available": true,
  "version": "0.1.0"
}
```

---

## 5. Synchronized Playback and UI

### 5.1 In-Browser Audio Player with Script Synchronization

**Frontend Architecture**:
- After render completes, the page displays:
  - An HTML5 `<audio>` player with controls (play, pause, seek, volume)
  - A script display panel showing the full script with blocks (scene headings, dialogue, action)
- JavaScript fetches the timing JSON and renders each block as a DOM element with `data-start` and `data-end` attributes
- On audio `timeupdate` event, the script highlights the current block (where `currentTime >= start && currentTime < end`)
- Auto-scrolling keeps the current block in view
- Clicking on a script block seeks the audio to that block's start time

**Timing Track Generation** (Backend):
- `RenderService` needs to be extended to optionally collect timing data during rendering
- Add a `collect_timing: bool = False` parameter to `RenderService.render()`
- When enabled, maintain a list of `TimingBlock` objects:
  ```python
  @dataclass
  class TimingBlock:
      type: str  # "scene_heading", "dialogue", "action"
      text: str
      character: str | None  # for dialogue
      start: float  # seconds
      end: float
  ```
- As each block's audio is added to the mixer, record the current position before and after
- Include pauses in the timeline (so `start` includes preceding pauses)
- At the end, include the timing list in `RenderResult` (new attribute)
- The frontend uses this to synchronize highlighting

**Why not WebVTT?**
- WebVTT is designed for subtitles (dialogue only), but we want to display full script structure (scene headings, actions)
- Custom JSON gives full control over styling and behavior
- Could be converted to WebVTT if needed for accessibility

**User Experience**:
- Clean, readable script display with typography distinguishing elements:
  - Scene headings: bold, all-caps, maybe different color
  - Dialogue: character name above line, indented
  - Action: italic or smaller font
- Current line highlighted with background color
- Optional: Show a "speaking" indicator (microphone icon) next to current character name
- Audio player can be fixed at bottom or top of page

---

## 6. Audio Output Delivery Strategy (Legacy)

### 6.1 File-Based Delivery (for direct download)

**Note**: This is still available as an alternative to synchronized playback. The `/render` endpoint can include a query parameter `?download=true` to return the audio file directly instead of JSON.

**Process**:
1. Render script to a temporary WAV file using `RenderService.render(output=temp_wav_path)`
2. If client requested MP3:
   - Check if `ffmpeg` is available (already checked during render if MP3 output)
   - Convert temp WAV to temp MP3 using `ffmpeg` subprocess
   - Delete temp WAV
   - Send MP3 file
3. If client requested WAV: send the temp WAV directly
4. After response, delete temporary file(s)

**Why not true streaming?**
- WAV format requires file size in header; cannot stream without knowing total size upfront
- Could stream raw PCM but browsers expect container formats
- MP3 conversion requires complete WAV file anyway
- Render time is dominated by TTS synthesis (seconds to minutes), so file generation latency is acceptable
- Simpler error handling: if render fails, return error without partial data

**Performance considerations**:
- Use `tempfile.NamedTemporaryFile(delete=False)` to create temp files in system temp dir
- Set appropriate permissions (0600)
- Cleanup via `@app.after_request` or context manager with `try/finally`
- Consider using a background thread for cleanup if many concurrent users

### 6.2 Alternative: Streaming with Server-Sent Events (Future)

If real-time progress is desired:
- Use WebSocket or SSE to send progress updates (scene count, dialogue count, ETA)
- Still deliver final file as download
- Not needed for MVP

---

## 7. Modifications to Existing Code

### 7.1 Required Changes

#### A. `config/settings.py`: Add programmatic Config construction

**Current state**: `Config.load()` reads from YAML file; `Config._from_dict()` exists but is internal.

**Change needed**: Make `_from_dict` public or add a `Config.from_dict()` classmethod.

```python
# In settings.py
@classmethod
def from_dict(cls, data: dict) -> "Config":
    """Create Config from a dictionary (e.g., from web form)."""
    return cls._from_dict(data)
```

**Why**: Web form data will be a dict; we need to construct Config without a file.

**Impact**: Low. Just expose existing logic.

#### A2. `parser/fountain.py`: Add `parse_string()` method

**Current state**: `FountainParser.parse()` only accepts a `Path` and reads from disk.

**Change needed**: Add a `parse_string(text: str, title: str | None = None) -> Script` method that parses Fountain text directly from a string. The web layer receives script text from a textarea or uploaded file — writing it to a temp file just to parse it is unnecessary I/O.

```python
def parse_string(self, text: str, title: str | None = None) -> Script:
    """Parse Fountain text from a string."""
    script = Script(title=title)
    # ... same state machine logic, iterating over text.splitlines()
```

**Implementation**: Factor the core line-processing loop out of `parse()` into a shared `_parse_lines(lines, script)` method. Both `parse()` and `parse_string()` delegate to it.

**Impact**: Low-moderate. Refactors internal loop but no behavior change for existing callers.

#### A3. `services.py`: Add `render_from_string()` method

**Current state**: `RenderService.render()` takes `script_path: Path`.

**Change needed**: Add `render_from_string(script_text: str, output: str | Path | None = None, collect_timing: bool = False) -> RenderResult` that uses `FountainParser.parse_string()` instead of `parse(path)`. Avoids writing pasted scripts to temp files.

**Impact**: Low. Thin wrapper that calls the same internal logic after parsing differently.

#### B. `services.py`: Allow config overrides for voice manager

**Current state**: `RenderService.__init__` takes a `VoiceManager` already configured with overrides.

**Change needed**: None! The CLI already does:
```python
voice_mgr = VoiceManager(tts)
if config_obj.voices:
    for character, voice in config_obj.voices.items():
        voice_mgr.set_character_voice(character, voice)
```
We'll replicate this pattern in the web layer.

#### C. `services.py`: Allow custom cache directory for TTS

**Current state**: `CachedTTSBackend` uses default cache dir `~/.cache/drinkingfountain/tts`.

**Change needed**: Optional, but we may want to use a per-request temp cache to avoid disk bloat from web users. However, caching is beneficial for repeated renders of same script.

**Options**:
1. Use a shared cache (current default) – simpler, benefits all users
2. Use a temp cache per request and delete after – more isolated but loses caching benefits

**Recommendation**: Keep shared cache. It's harmless and speeds up repeated renders. No code change needed; just pass `cache_dir` if we want custom location.

#### D. `services.py`: Add timing collection capability

**Current state**: `RenderService.render()` does not collect per-block timing information.

**Change needed**: Extend `RenderService` to optionally collect timing data.

**Implementation**:
- Add a new dataclass `TimingBlock` in `services.py`:
  ```python
  @dataclass
  class TimingBlock:
      type: str  # "scene_heading", "dialogue", "action"
      text: str
      character: str | None = None
      start: float = 0.0  # seconds
      end: float = 0.0
  ```
- Add `collect_timing: bool = False` parameter to both `render()` and `render_from_string()`
- Add `timing_blocks: list[TimingBlock] | None` attribute to `RenderResult`

**Hook point** — The render loop in `render()` (lines 307-421 of `services.py`) iterates scenes and blocks. The `AudioMixer` already tracks `state.current_position` (float, in seconds). The concrete insertion points are:

1. **Scene headings** (line ~326-359): Read `mixer.state.current_position` before `mixer.add_scene_heading()`, read again after. Record `TimingBlock(type="scene_heading", text=heading.content, start=before, end=after)`.

2. **Dialogue** (line ~364-380): Read position before `mixer.add_dialogue()`, read after. Record `TimingBlock(type="dialogue", text=block.content, character=block.character, start=before, end=after)`.

3. **Action/narrative** (line ~383-406): Read position before `mixer.add_narrative()`, read after. Record `TimingBlock(type="action", text=block.content, start=before, end=after)`.

4. **Scene transition pauses** (line ~418-421): After `self._add_silence()`, update a running `cumulative_offset` that tracks time added between scenes (since the mixer is recreated per-scene, its `current_position` resets). Each scene's timing blocks need `cumulative_offset` added to their start/end values.

**Impact**: Moderate. Requires careful integration but does not change existing behavior when `collect_timing=False` (default).

#### E. `audio/mixer.py`: Ensure `StreamingWAVWriter` and `StreamingAudioPlayer` work with temp files

**Current state**: Already used by `RenderService.render()` for file output. Works fine.

**Change needed**: None.

---

### 7.2 New Files to Create

All web files live inside the `web` package so Flask's `__name__`-based template/static discovery works automatically:

```
src/drinkingfountain/web/
    __init__.py          # create_app() factory
    app.py               # routes, build_config_from_form(), RenderStore
    templates/
        index.html       # Jinja2 UI template
    static/
        css/
            style.css    # Custom styling
        js/
            app.js       # Client-side logic
```

#### `src/drinkingfountain/web/app.py`

Main Flask application:
- Imports Flask, render_template, request, send_file, jsonify
- Imports drinkingfountain services
- Defines routes: `/`, `/render`, `/audio/<render_id>`, `/timing/<render_id>`, `/api/voices`, `/api/health`
- Contains helper: `build_config_from_form(form_data) -> Config`
- Contains `RenderStore` class: TTL-based dict mapping `render_id` → `{audio_path, timing_path, created_at}` with periodic eviction (default 30-minute TTL, max 50 entries)
- Contains render timeout wrapper (default 5 minutes) using `threading.Timer` or `signal.alarm`
- Main app factory: `create_app(config_overrides=None) -> Flask`

#### `src/drinkingfountain/web/templates/index.html`

Jinja2 template for main UI:
- HTML structure with Bootstrap 5 (CDN)
- Two-panel layout: input form + results area (hidden until render completes)
- Results area: HTML5 `<audio>` player + synchronized script display panel
- Configuration sections (collapsible)
- Submit button with loading state
- JavaScript to fetch voices and populate dropdowns

#### `src/drinkingfountain/web/static/js/app.js`

Client-side logic:
- Fetch voices on load, populate dropdowns
- Dynamic character voice mapping table (add/remove rows)
- Form submission via `fetch('/render')`, parse JSON response
- `setupPlayer(audioUrl, timingUrl)`: set audio src, fetch timing JSON, render script blocks with `data-start`/`data-end`, wire `timeupdate` for highlighting and auto-scroll
- Click-to-seek on script blocks

#### `src/drinkingfountain/web/static/css/style.css`

Custom CSS for script display (block types, active highlight, audio player positioning).

### 7.3 Configuration for Web Mode

**Approach**: The web app will use default config values, but allow overrides via form. No YAML file needed.

**Default Config** (same as CLI defaults):
- Audio: sample_rate=22050, channels=mono, normalize=True, target_level=-3.0
- Timing: pause_between_lines=0.3, pause_after_scene_heading=1.0, pause_between_scenes=2.0
- Narrator: enabled=True, voice=None (auto-select first), expand_int_ext=True, pause_before_narrative=0.5, pause_after_narrative=0.3
- Voices: empty dict (auto-assign)

**Form to Config mapping**:
- Simple fields: direct assignment
- Checkboxes: boolean conversion
- Numbers: float/int conversion with validation
- Character voice overrides: dict from dynamic table

---

## 8. Step-by-Step Implementation Plan

### Phase 1: Project Setup and Dependencies

1. **Flask is already a core dependency** (`flask>=3.0.0` in `pyproject.toml` `dependencies`).
   No change needed. Flask is lightweight (~200KB, transitive deps are Werkzeug and Jinja2 which are small). Keeping it as a core dep avoids the complexity of optional extras.

2. **Create project structure** (all inside the web package):
   ```
   src/drinkingfountain/web/
       __init__.py
       app.py
       templates/
           index.html
       static/
           css/
               style.css
           js/
               app.js
   ```

3. **Install dependencies**: `uv sync` or `pip install -e .`

### Phase 2: Core Flask Application

1. **Implement `create_app()` factory** in `src/drinkingfountain/web/__init__.py` or `app.py`:
   - Initialize Flask app
   - Configure upload folder (temp), max content length (e.g., 10MB)
   - Register routes

2. **Implement `build_config_from_form()` helper**:
   - Extract form fields from `request.form`
   - Convert types (int, float, bool)
   - Build `Config` object using `Config.from_dict()` (or direct dataclass construction)
   - Handle missing fields with defaults
   - Validate with `config.validate()` and return errors if invalid

3. **Implement `/api/voices` route**:
   - Create `VoiceService()` or use `PiperTTSBackend` directly
   - Return JSON list of voices
   - Handle errors (Piper not installed)

4. **Implement `/api/health` route**:
   - Check `PiperTTSBackend.is_available()`
   - Return status JSON

### Phase 3: Render Endpoint

1. **Implement `POST /render`**:
   - Accept form data with script (text or file)
   - Read script content into string
   - Build `Config` from form
   - Create temp file for output (using `tempfile.NamedTemporaryFile(delete=False, suffix=format)`)
   - Initialize services (TTS, VoiceManager, RenderService)
   - Apply voice overrides from config or form
   - Call `service.render(script_path=?, output=temp_path)` – need to handle script as file or StringIO
     - Option: Write script string to a temp file and pass Path
   - Handle exceptions and return JSON error with appropriate status code
   - On success: `return send_file(temp_path, as_attachment=True, download_name=...)`
   - Register `@app.after_request` to cleanup temp file after response

2. **Handle MP3 conversion**:
   - If output_format == 'mp3' and ffmpeg available:
     - Render to temp WAV first
     - Convert to temp MP3 using `subprocess.run(['ffmpeg', ...])`
     - Send MP3, cleanup both temp files
   - If ffmpeg not available: return error suggesting WAV format

3. **Progress indication (optional for MVP)**:
   - Since render is synchronous, the browser will show loading spinner until response
   - That's acceptable for MVP; can add async job queue later

### Phase 4: UI Development (Updated for Synchronized Playback)

1. **Create `templates/index.html`**:
   - Basic HTML5 structure
   - Include Bootstrap 5 CSS/JS from CDN
   - Two main sections:
     - **Input Form**: script textarea/file upload, configuration (collapsible), render button
     - **Results Area** (hidden initially):
       - Audio player: `<audio controls>` element with source set to audio_url
       - Script display panel: container for script blocks (each with data-start, data-end)
   - Submit button: "Render Audio" with spinner
   - Results: show after render completes

2. **JavaScript in `static/js/app.js`**:
   - On page load: `fetch('/api/voices')` → populate narrator voice select and character voice selects
   - Handle file input change: if file selected, show filename, optionally disable textarea
   - Form submit: `fetch('/render', { method: 'POST', body: formData })`
     - On success: show results area, call `setupPlayer(response.audio_url, response.timing_url)`
     - On error: display error message
   - `setupPlayer(audioUrl, timingUrl)`:
     - Set audio element `src = audioUrl`
     - `fetch(timingUrl)` → get timing JSON
     - Render script blocks: for each block in timing.blocks, create a `<div class="block type-{type}" data-start={start} data-end={end}>`
       - Content: for dialogue: character name in `<strong>`, text in `<p>`; for action/heading: text directly
     - Add `timeupdate` event listener to audio element:
       - Find block where `audio.currentTime >= start && audio.currentTime < end`
       - Add `active` class to that block, remove from others
       - Scroll block into view (smooth if not manual scroll)
     - Add click handler to blocks: `audio.currentTime = block.dataset.start`
   - Optional: Keyboard shortcuts (space to play/pause)

3. **Styling** (CSS)**:
   - Script panel: scrollable, max-height, with padding
   - Block styling:
     - `.block` padding, margin-bottom
     - `.block.dialogue` indented, character name bold
     - `.block.scene_heading` bold, all-caps, maybe border-top
     - `.block.action` italic, smaller font, gray color
     - `.block.active` highlight with background color (e.g., yellow)
   - Audio player fixed at bottom or top for easy access

4. **Enhancements** (post-MVP):
   - Show current time and total duration
   - Seek bar that shows progress through script (maybe highlight blocks on seek bar)
   - Voice indicators: show which voice is speaking for dialogue

### Phase 5: Testing and Refinement

1. **Unit tests** (optional but good):
   - Test `build_config_from_form()` with various inputs
   - Test `/api/voices` endpoint
   - Mock `RenderService` to test error handling

2. **Manual testing**:
   - Start Flask dev server: `python -m drinkingfountain.web.app` (need to add entry point)
   - Open browser, test with sample script
   - Verify audio plays correctly
   - Test error cases: no script, invalid config, missing voice

3. **Error handling improvements**:
   - Catch `FileNotFoundError` (voice missing) → user-friendly message
   - Catch `RuntimeError` (TTS failure) → show error
   - Handle large uploads (set `MAX_CONTENT_LENGTH`)

4. **Security considerations** (for local use, low risk):
   - Validate script size (e.g., max 1MB)
   - Sanitize character names? Not needed; they're just strings
   - Temp file cleanup: ensure always deleted (use `try/finally` or `atexit`)

5. **Production deployment** (optional):
   - Add Gunicorn config: `gunicorn -w 4 "drinkingfountain.web.app:create_app()"`
   - Consider using a reverse proxy (nginx) if needed
   - Document environment variables (e.g., `VOICES_DIR`, `CACHE_DIR`)

### Phase 6: Documentation and Packaging

1. **Update README.md**:
   - Add section "Web Interface"
   - Explain how to start: `python -m drinkingfountain.web` or `drinkingfountain-web` script
   - Screenshot (if available)
   - Note that Flask must be installed

2. **Add console script entry point** (optional):
   In `pyproject.toml`:
   ```toml
   [project.scripts]
   drinkingfountain = "drinkingfountain.cli:main"
   drinkingfountain-web = "drinkingfountain.web.cli:main"  # optional wrapper
   ```

3. **Create `src/drinkingfountain/web/cli.py`** (optional):
   - `main()` function that calls `create_app().run(debug=True, host='0.0.0.0', port=5000)`
   - Allows `drinkingfountain-web` command

4. **Update installation instructions**:
   - Flask is already a core dependency — no separate install step needed.
   - Document how to start the web server: `drinkingfountain-web` or `python -m drinkingfountain.web`

---

## 9. Dependencies and Prerequisites

### New Dependencies
- **Flask** >= 3.0.0 (lightweight, no extra dependencies beyond Werkzeug/Jinja2)

### Existing Dependencies (already covered)
- `piper-tts` – core TTS
- `pydub` – audio manipulation
- `pyyaml` – config parsing (not needed for web but used)
- `simpleaudio` – optional for playback (not needed for web)
- `soundfile` – audio file I/O
- `numpy` – audio arrays

### System Requirements
- **Python**: 3.10+ (already required)
- **ffmpeg**: Only needed for MP3 output (same as CLI)
- **Piper TTS voice models**: Must be installed separately (web UI can show message if none found)

### Optional (for production)
- **Gunicorn** or **uWSGI** WSGI server
- **nginx** reverse proxy

---

## 10. Error Handling and User Experience

### Common Errors and Messages

| Error | Cause | Web UI Response |
|-------|-------|-----------------|
| No script provided | Empty textarea and no file | Inline error: "Please enter a script or upload a file." |
| Script too large | > configured limit | Error page: "Script too large. Maximum size: X MB." |
| Invalid config value | Negative pause, invalid sample rate | Inline error highlighting the field |
| Piper not installed | `piper-tts` missing | Error page with install instructions |
| No voices available | No voice models downloaded | Error page: "No voice models found. Download voices first." |
| Voice not found | Character mapped to non-existent voice | Warning in results: "Voice 'X' not found, using default." |
| TTS synthesis failure | Voice model corrupted, out of memory | Error page with details |
| Disk full / permission error | Cannot write temp file | Error page: "Cannot write temporary files. Check disk space." |
| ffmpeg missing (MP3) | User requested MP3 but ffmpeg not installed | Error: "MP3 export requires ffmpeg. Please install or choose WAV." |

### Validation Strategy
- **Client-side**: HTML5 required fields, pattern validation for numbers
- **Server-side**: All form data validated via `Config.validate()` and additional checks (script non-empty)
- **Graceful degradation**: If optional features fail (narrator voice missing), disable narrator and continue

---

## 11. Security Considerations

**Threat model**: This is a local or trusted-network tool, not a public internet service. Still, basic precautions:

1. **File uploads**:
   - Only accept `.fountain` extension (but content-type can be faked)
   - Limit size (e.g., 10MB) via `app.config['MAX_CONTENT_LENGTH']`
   - Store uploads in system temp dir with random names
   - Delete after processing

2. **Path traversal**: Not applicable; we don't use user-provided paths for file I/O except temp files (use `tempfile` module).

3. **Command injection**: No user input goes to shell except possibly `ffmpeg` command. Use list args (not `shell=True`) – already done in `services.py`.

4. **Denial of service**:
   - Limit concurrent requests? Flask dev server is single-threaded by default; production with Gunicorn can set `--workers`.
   - Long-running renders could tie up workers. Consider adding a timeout? Not needed for local use.

5. **Information disclosure**: Error messages may expose file paths. Sanitize logs, but for local use it's fine.

---

## 12. Future Enhancements (Post-MVP)

- **Async rendering with progress**: Use Celery or RQ to run render in background; poll status via AJAX
- **Voice testing widget**: Click a voice to hear a sample phrase
- **Script preview**: Parse script and show scene/character list before rendering
- **Configuration presets**: Save/load config sets
- **Batch rendering**: Upload multiple scripts, render queue
- **User accounts**: Not needed for local use
- **REST API only**: Separate frontend (React/Vue) from backend; but Flask templates are fine for now
- **Docker container**: Package entire app with voices pre-installed
- **WebSocket for real-time logs**: Stream render progress to UI

---

## 13. Implementation Checklist

- [x] Expose `Config._from_dict()` as public `Config.from_dict()`
- [x] Add `FountainParser.parse_string()` method (parse from string, not just file)
- [x] Reset parser line numbers for each file/string parse
- [x] Add `RenderService.render_from_string()` method (render from script text)
- [x] Add `TimingBlock` dataclass and timing collection to `RenderService.render()` / `render_from_string()`
- [x] Create `src/drinkingfountain/web/__init__.py` with `create_app()`
- [x] Create `src/drinkingfountain/web/app.py` with routes and `build_config_from_form()` helper
- [x] Implement render store with TTL-based eviction for render results
- [x] Implement render timeout response (default 5 minutes)
- [x] Implement `/api/health` endpoint
- [x] Implement `/api/voices` endpoint
- [x] Implement `POST /render` endpoint with temp file handling
- [x] Implement `GET /audio/<render_id>` endpoint
- [x] Implement `GET /timing/<render_id>` endpoint
- [x] Create `src/drinkingfountain/web/templates/index.html` with form and synchronized player
- [x] Create `src/drinkingfountain/web/static/js/app.js` for dynamic voice loading and playback sync
- [x] Create `src/drinkingfountain/web/static/css/style.css`
- [x] Add `drinkingfountain-web` console script entry point in `pyproject.toml`
- [x] Add automated tests for web config, render store cleanup, and render endpoint behavior
- [ ] Replace Bootstrap CDN dependencies or document that the web UI needs network access for styling
- [ ] Improve frontend validation for missing script/file, unsupported output format, and unavailable voices
- [ ] Add manual browser QA with real Piper voices installed
- [ ] Decide whether long renders need a background job queue instead of in-request execution
- [ ] Manual end-to-end test: render a sample script via web UI

---

## 14. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Piper TTS not thread-safe | Low | Medium | Use per-request instances; avoid sharing `PiperTTSBackend` across threads |
| Memory bloat from concurrent renders | Medium | Medium | Each render processes scene-by-scene (already streaming), so memory is bounded |
| Temp file accumulation if crashes | Low | Low | Use `atexit` cleanup, `try/finally`, and periodic temp dir cleanup |
| Slow renders block workers | High | Medium | Acceptable for low concurrency; production can increase worker count |
| Browser compatibility | Low | Low | Use standard HTML5 and Flask's `send_file` (works in all modern browsers) |
| ffmpeg not installed for MP3 | Medium | Low | Detect and show error; fallback to WAV |

---

## 15. Conclusion

This plan provides a clear path to adding a web UI to DrinkingFountain with minimal changes to the existing codebase. Flask is the recommended framework due to its simplicity, flexibility, and seamless integration with the current synchronous, service-oriented architecture. The implementation can be completed in 5-7 phases, with the core rendering functionality working after Phase 3 and a polished UI after Phase 4.

All existing business logic (parsing, TTS, mixing) will be reused as-is, ensuring consistency with the CLI behavior. The web layer acts purely as a presentation and integration layer.
