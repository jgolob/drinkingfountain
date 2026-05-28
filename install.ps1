# DrinkingFountain Installer for Windows
# PowerShell script for automated installation

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Header($text) {
    Write-Host ""
    Write-Host "====================================================================" -ForegroundColor Blue
    Write-Host ($text.PadLeft(30 + [math]::Floor($text.Length/2)).PadRight(60)) -ForegroundColor Blue -Bold
    Write-Host "====================================================================" -ForegroundColor Blue
    Write-Host ""
}

function Write-Success($text) {
    Write-Host "✓ $text" -ForegroundColor Green
}

function Write-Error($text) {
    Write-Host "✗ $text" -ForegroundColor Red
}

function Write-Warning($text) {
    Write-Host "⚠ $text" -ForegroundColor Yellow
}

function Write-Info($text) {
    Write-Host "ℹ $text" -ForegroundColor Cyan
}

function Write-Step($text) {
    Write-Host ""
    Write-Host "→ $text" -ForegroundColor Blue -Bold
}

function Confirm-YesNo($question, $default = $true) {
    $suffix = if ($default) { " [Y/n]" } else { " [y/N]" }
    $response = Read-Host "$question$suffix"
    if ([string]::IsNullOrWhiteSpace($response)) {
        return $default
    }
    return $response -match '^[Yy]'
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path $ScriptDir

# Default values
$UseVenv = $true
$DownloadVoice = $true
$DefaultVoice = "en_US-amy-medium"
$CreateConfig = $true
$ConfigLocation = "local"  # "local" or "home"

Write-Header "DrinkingFountain Installer"
Write-Info "This installer will set up DrinkingFountain on your system."
Write-Info "It will install dependencies, download a voice model, and create a config file."
Write-Host ""

# Check Python
Write-Step "Checking Python version..."

if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command python3 -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH"
    Write-Info "Please install Python 3.10 or newer from https://www.python.org/"
    exit 1
}

# Determine which python command to use
$PythonCmd = "python"
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $PythonCmd = "python3"
}

# Get Python version
$PythonVersion = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$RequiredVersion = "3.10"

if ([version]$PythonVersion -lt [version]$RequiredVersion) {
    Write-Error "Python $PythonVersion detected"
    Write-Error "DrinkingFountain requires Python $RequiredVersion or newer"
    exit 1
}

Write-Success "Python $PythonVersion is compatible"

# Virtual environment
Write-Step "Virtual environment setup"
if (Confirm-YesNo "Create a virtual environment? (recommended)" $true) {
    $UseVenv = $true
    $VenvPath = Join-Path $ProjectRoot ".venv"

    if (Test-Path $VenvPath) {
        Write-Warning "Virtual environment already exists at $VenvPath"
        if (Confirm-YesNo "Delete and recreate?" $false) {
            Remove-Item -Recurse -Force $VenvPath
        } else {
            Write-Info "Using existing virtual environment"
        }
    }

    if (-not (Test-Path $VenvPath)) {
        Write-Info "Creating virtual environment..."
        & $PythonCmd -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to create virtual environment"
            exit 1
        }
        Write-Success "Virtual environment created"
    }

    # Activate virtual environment
    $Env:VIRTUAL_ENV = $VenvPath
    $Env:Path = Join-Path $VenvPath "Scripts" + ";" + $Env:Path
    $PythonCmd = Join-Path $VenvPath "Scripts\python.exe"
} else {
    $UseVenv = $false
    Write-Warning "Using system Python. Consider using a virtual environment to avoid conflicts."
}

# Package manager
Write-Step "Checking package manager..."

$UvAvailable = $false
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $UvAvailable = $true
}

if ($UvAvailable) {
    Write-Info "uv is available - will use it for fast dependency resolution"
    $UseUv = Confirm-YesNo "Use uv for installation? (recommended)" $true
} else {
    $PipAvailable = & $PythonCmd -m pip --version 2>$null
    if (-not $PipAvailable) {
        Write-Error "Neither uv nor pip is available. Please install pip first."
        exit 1
    }
    $UseUv = $false
    Write-Info "Will use pip for installation"
}

# Install dependencies
Write-Step "Installing dependencies..."

if ($UseUv) {
    Write-Info "Using uv for installation (fast)..."
    uv sync
} else {
    Write-Info "Using pip for installation..."
    & $PythonCmd -m pip install --upgrade pip
    & $PythonCmd -m pip install -e .
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies"
    exit 1
}

Write-Success "Dependencies installed successfully"

# Check for ffmpeg
Write-Step "Checking for ffmpeg..."

$FfmpegInstalled = $false
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    $FfmpegInstalled = $true
    Write-Success "ffmpeg is already installed"
} else {
    Write-Warning "ffmpeg is not installed (needed for MP3 export)"
    if (Confirm-YesNo "Attempt to install ffmpeg automatically?" $false) {
        Write-Info "Automatic ffmpeg installation on Windows requires manual steps."
        Write-Info "Please download ffmpeg from https://ffmpeg.org/download.html"
        Write-Info "Extract and add the bin directory to your PATH."
        Write-Info "Alternatively, use Chocolatey: choco install ffmpeg"
    } else {
        Write-Info "Skipping ffmpeg installation. You can install it later."
        Write-Info "MP3 export will not be available until ffmpeg is installed."
    }
}

# Check for simpleaudio
Write-Step "Checking for simpleaudio (audio playback)..."

$SimpleaudioInstalled = $false
try {
    Import-Module -Name simpleaudio -ErrorAction Stop
    $SimpleaudioInstalled = $true
    Write-Success "simpleaudio is already installed"
} catch {
    Write-Warning "simpleaudio is not installed (needed for direct playback)"
    if (Confirm-YesNo "Install simpleaudio?" $true) {
        Write-Info "Installing simpleaudio..."
        & $PythonCmd -m pip install simpleaudio
        if ($LASTEXITCODE -eq 0) {
            Write-Success "simpleaudio installed"
            $SimpleaudioInstalled = $true
        } else {
            Write-Warning "simpleaudio installation failed"
            Write-Info "You can still export to files. Install simpleaudio later for playback."
        }
    } else {
        Write-Info "Skipping simpleaudio installation"
    }
}

# Voice download
Write-Step "Voice model setup"

if (Confirm-YesNo "Download a default voice model? (recommended)" $true) {
    Write-Info "Available default options:"
    Write-Info "  en_US-amy-medium  (American English, medium quality)"
    Write-Info "  en_US-john-medium (American English, medium quality)"
    Write-Info "  en_GB-james-high  (British English, high quality)"
    $voiceInput = Read-Host "Enter voice ID [en_US-amy-medium]"
    $SelectedVoice = if ([string]::IsNullOrWhiteSpace($voiceInput)) { "en_US-amy-medium" } else { $voiceInput }

    Write-Info "Downloading voice model '$SelectedVoice'..."
    Write-Info "This may take a few minutes..."

    if ($UseVenv) {
        & "$ProjectRoot\.venv\Scripts\drinkingfountain.exe" voices download $SelectedVoice
    } else {
        drinkingfountain voices download $SelectedVoice
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Voice model '$SelectedVoice' downloaded"
        $DefaultVoice = $SelectedVoice
    } else {
        Write-Error "Failed to download voice"
        Write-Info "You can download later with: drinkingfountain voices download $SelectedVoice"
        $DefaultVoice = ""
    }
} else {
    Write-Info "Skipping voice download"
    Write-Info "Remember to download at least one voice before using:"
    Write-Info "  drinkingfountain voices download en_US-amy-medium"
    $DefaultVoice = ""
}

# Config file
Write-Step "Configuration file"

if (Confirm-YesNo "Create a sample configuration file?" $true) {
    Write-Info "Where should the config file be created?"
    Write-Info "  1. Local directory (.\drinkingfountain.yaml) - recommended for project-specific settings"
    Write-Info "  2. Home directory (%APPDATA%\drinkingfountain\config.yaml) - for global settings"
    $configChoice = Read-Host "Choose location [1]"
    if ([string]::IsNullOrWhiteSpace($configChoice)) { $configChoice = "1" }

    if ($configChoice -eq "2") {
        $ConfigPath = Join-Path $Env:APPDATA "drinkingfountain\config.yaml"
    } else {
        $ConfigPath = Join-Path $ProjectRoot "drinkingfountain.yaml"
    }

    $ConfigDir = Split-Path $ConfigPath -Parent
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }

    $VoiceForConfig = if ($DefaultVoice) { $DefaultVoice } else { "en_US-amy-medium" }

    $ConfigContent = @"
# DrinkingFountain Configuration
# See https://github.com/yourusername/drinkingfountain for more info

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
  # Example: assign voices to characters
  # JOHN: $VoiceForConfig
  # SARAH: en_US-sarah-medium
  # NARRATOR: en_US-amy-medium

# Note: If you don't assign voices here, characters will be auto-assigned
# from available voices. The narrator voice (if present) is reserved.
"@

    $ConfigContent | Out-File -FilePath $ConfigPath -Encoding UTF8
    Write-Success "Configuration file created at $ConfigPath"
    Write-Info "Edit this file to customize voice assignments and settings."
} else {
    Write-Info "Skipping config file creation"
}

# Verification
Write-Step "Verifying installation..."

$DrinkingFountainCmd = if ($UseVenv) { "$ProjectRoot\.venv\Scripts\drinkingfountain.exe" } else { "drinkingfountain" }

try {
    $VersionOutput = & $DrinkingFountainCmd --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "DrinkingFountain is installed and working!"
        Write-Info "Version: $VersionOutput"
    } else {
        Write-Warning "Verification failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Warning "Verification failed: $_"
}

Write-Header "Installation Complete!"
Write-Success "DrinkingFountain has been successfully installed!"

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Bold
Write-Host "  1. If you haven't downloaded a voice, do it now:"
Write-Host "     drinkingfountain voices download en_US-amy-medium"
Write-Host "  2. Create a Fountain script (e.g., script.fountain)"
Write-Host "  3. Render it to audio:"
Write-Host "     drinkingfountain render script.fountain -o output.wav"
Write-Host ""
Write-Host "Or play directly through speakers (if simpleaudio installed):"
Write-Host "     drinkingfountain render script.fountain"
Write-Host ""
Write-Host "Documentation:" -ForegroundColor Bold
Write-Host "  - README.md: Full documentation"
Write-Host "  - https://fountain.io: Fountain format spec"
Write-Host ""
Write-Host "Happy scripting! 🎭" -ForegroundColor Green
Write-Host ""
