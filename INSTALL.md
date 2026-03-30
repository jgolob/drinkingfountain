# Installation Guide

This guide covers installing DrinkingFountain using the automated installer or manual methods.

## Table of Contents

- [Quick Start](#quick-start)
- [Automated Installer](#automated-installer)
  - [macOS / Linux](#macos--linux)
  - [Windows](#windows)
  - [What the Installer Does](#what-the-installer-does)
- [Manual Installation](#manual-installation)
  - [Prerequisites](#prerequisites)
  - [Step-by-Step Manual Install](#step-by-step-manual-install)
- [Post-Installation](#post-installation)
- [Troubleshooting](#troubleshooting)
- [Uninstallation](#uninstallation)

---

## Quick Start

The fastest way to get started:

**macOS / Linux:**
```bash
bash install.sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

That's it! The installer handles everything. After installation, see [Post-Installation](#post-installation) for next steps.

---

## Automated Installer

The automated installer provides a user-friendly, interactive installation experience.

### macOS / Linux

1. Open Terminal
2. Navigate to the DrinkingFountain directory:
   ```bash
   cd /path/to/drinkingfountain
   ```
3. Run the installer:
   ```bash
   bash install.sh
   ```
4. Follow the on-screen prompts

**Note**: If you get a permission error, you may need to make the script executable first:
```bash
chmod +x install.sh
./install.sh
```

### Windows

1. Open PowerShell (as Administrator is not required, but may help with ffmpeg installation)
2. Navigate to the DrinkingFountain directory:
   ```powershell
   cd C:\path\to\drinkingfountain
   ```
3. Run the installer:
   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
   Or if you've already set the execution policy to allow scripts:
   ```powershell
   .\install.ps1
   ```

**Note**: If PowerShell blocks script execution, use the `-ExecutionPolicy Bypass` flag as shown above.

### What the Installer Does

The installer performs the following steps:

1. **Python Check**: Verifies Python 3.10+ is installed
2. **Virtual Environment** (optional but recommended):
   - Creates `.venv/` in the project directory
   - Isolates dependencies from system Python
   - Can skip if you prefer system-wide installation
3. **Dependency Installation**:
   - Uses `uv` if available (fast, modern package manager)
   - Falls back to `pip` if uv is not installed
   - Installs all required Python packages
4. **ffmpeg Check**:
   - Detects if ffmpeg is already installed
   - On macOS/Linux: Can attempt automatic installation via Homebrew/apt/dnf/pacman
   - On Windows: Provides download instructions
   - ffmpeg is needed for MP3 export (optional)
5. **simpleaudio Installation**:
   - Installs the simpleaudio package for direct audio playback
   - Can skip if you only need file export
6. **Voice Model Download**:
   - Downloads a default voice model (en_US-amy-medium by default)
   - You can choose a different voice during installation
   - Voice models are ~100MB, so this may take a few minutes
7. **Configuration File**:
   - Creates a sample `drinkingfountain.yaml` (local) or user config
   - You can edit this later to customize settings
8. **Verification**:
   - Tests that the `drinkingfountain` command works
   - Reports the installed version

All steps are clearly indicated with colored output:
- ✓ Green checkmarks for success
- ⚠ Yellow warnings for non-critical issues
- ✗ Red X for failures
- ℹ Blue info messages

---

## Manual Installation

If the automated installer doesn't work for your system, follow these manual steps.

### Prerequisites

Before installing, ensure you have:

1. **Python 3.10 or newer**
   - Download from [python.org](https://www.python.org/downloads/)
   - Verify with: `python3 --version` (or `python --version` on Windows)

2. **Package manager**: Either `uv` (recommended) or `pip`
   - Install uv: `pip install uv`
   - pip comes with Python installations

3. **ffmpeg** (optional, for MP3 export)
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt-get install ffmpeg` (Debian/Ubuntu) or `sudo dnf install ffmpeg` (Fedora)
   - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

4. **simpleaudio** (optional, for playback)
   - Will be installed via pip automatically

### Step-by-Step Manual Install

#### 1. Clone or Download the Repository

```bash
git clone https://github.com/yourusername/drinkingfountain.git
cd drinkingfountain
```

Or download and extract the ZIP archive.

#### 2. Create Virtual Environment (Recommended)

```bash
python3 -m venv .venv
```

Activate it:
- macOS/Linux: `source .venv/bin/activate`
- Windows: `.venv\Scripts\activate`

#### 3. Install Dependencies

Using uv (recommended):
```bash
uv sync
```

Using pip:
```bash
pip install -e .
```

#### 4. Download a Voice Model

At least one voice model is required:

```bash
drinkingfountain voices download en_US-amy-medium
```

See [Voice Models](#voice-models) in README.md for more options.

#### 5. Create Configuration File (Optional)

Create `drinkingfountain.yaml` in your project directory or home config:

```bash
# Copy the example from README.md or create your own
# See README.md for full configuration options
```

#### 6. Test Installation

```bash
drinkingfountain --version
drinkingfountain voices list
```

---

## Post-Installation

After successful installation, you're ready to create audio from screenplays.

### First Steps

1. **Create a Fountain script** (e.g., `script.fountain`):

```fountain
INT. COFFEE SHOP - DAY

JOHN
(sipping coffee)
This is pretty good.

SARAH
I know, right? The new blend is amazing.
```

2. **Render to audio**:

Save to a file:
```bash
drinkingfountain render script.fountain -o output.wav
```

Or play directly (if simpleaudio installed):
```bash
drinkingfountain render script.fountain
```

3. **Configure voice assignments** (optional):

Edit your `drinkingfountain.yaml` to assign specific voices to characters:

```yaml
voices:
  JOHN: en_US-john-medium
  SARAH: en_US-sarah-medium
```

### Useful Commands

- List installed voices: `drinkingfountain voices list`
- See available voices: `drinkingfountain voices available`
- Download more voices: `drinkingfountain voices download <voice_id>`
- Test a voice: `drinkingfountain voices test en_US-amy-medium "Hello, world!"`
- Get help: `drinkingfountain --help`

---

## Troubleshooting

### Installer Issues

**"bash: install.sh: Permission denied"**
```bash
chmod +x install.sh
./install.sh
```

**PowerShell execution policy errors on Windows**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

**Python not found**
- Ensure Python 3.10+ is installed and in your PATH
- On macOS, you may need to install Python via Homebrew: `brew install python`
- On Windows, check "Add Python to PATH" during installation

**uv not found**
- The installer will fall back to pip automatically
- Or install uv first: `pip install uv`

### Installation Failures

**"Failed to install dependencies"**
- Check internet connection
- Ensure pip/uv is up to date: `pip install --upgrade pip`
- Try manual installation: `pip install -e .`

**"Voice download failed"**
- Check internet connection
- The voice model is ~100MB; ensure sufficient disk space
- Try downloading manually: `drinkingfountain voices download en_US-amy-medium`
- If issues persist, download from HuggingFace directly: https://huggingface.co/rhasspy/piper-voices

**"ffmpeg not found" after installation**
- ffmpeg is optional; use WAV format instead of MP3
- Or install ffmpeg manually (see Prerequisites above)
- Ensure ffmpeg is in your PATH after installation

**"No module named 'simpleaudio'"**
- simpleaudio may have failed to install
- Install manually: `pip install simpleaudio`
- On Linux, you may need system dependencies:
  - Ubuntu/Debian: `sudo apt-get install portaudio19-dev python3-dev`
  - Fedora: `sudo dnf install portaudio-devel python3-devel`
  - Then: `pip install simpleaudio`

### Runtime Issues

**"No voices available" or "Voice model not found"**
- Download at least one voice: `drinkingfountain voices download en_US-amy-medium`
- Check voice directory: `~/.local/share/piper-tts/voices/` (Linux/macOS) or `%APPDATA%/local/share/piper-tts/voices/` (Windows)

**MP3 export fails**
- Ensure ffmpeg is installed and in PATH: `ffmpeg -version`
- Use WAV format instead: `-o output.wav`

**Poor audio quality**
- Try a higher quality voice: `en_US-amy-high` instead of `en_US-amy-medium`
- Check sample rate in config: use 22050 Hz for most Piper voices
- Ensure voice model downloaded completely (check file size ~100MB+)

**"No dialogue found in script"**
- Ensure character names are in ALL CAPS
- There must be a blank line before each character name
- Dialogue lines must directly follow the character name
- See [Fountain Format](https://fountain.io) for full spec

---

## Uninstallation

To remove DrinkingFountain:

1. Delete the project directory (or just the virtual environment if you want to keep your scripts)
2. Optionally remove voice models:
   - Linux/macOS: `rm -rf ~/.local/share/piper-tts/`
   - Windows: `rmdir /s %APPDATA%\local\share\piper-tts\`
3. Optionally remove user config: `~/.config/drinkingfountain/` or `%APPDATA%\drinkingfountain\`

If you installed to system Python (no virtual environment), you can also:
```bash
pip uninstall drinkingfountain
```

---

## Additional Resources

- **README.md**: Full documentation and CLI reference
- **Fountain spec**: https://fountain.io
- **Piper TTS**: https://github.com/rhasspy/piper
- **Voice models**: https://huggingface.co/rhasspy/piper-voices

---

## Getting Help

If you encounter issues not covered here:

1. Check the [Troubleshooting](#troubleshooting) section in README.md
2. Search existing [GitHub Issues](https://github.com/yourusername/drinkingfountain/issues)
3. Open a new issue with:
   - Your operating system
   - Python version (`python3 --version`)
   - Error message and steps to reproduce
   - Output from `drinkingfountain --verbose render script.fountain`

---

*Happy scripting! May your table reads be ever in tune! 🎭*
