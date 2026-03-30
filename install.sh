#!/usr/bin/env bash

# DrinkingFountain Installer
# A user-friendly installation script for macOS and Linux

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Default values
USE_VENV=true
INSTALL_FFMPEG=false
INSTALL_SIMPLEAUDIO=true
DOWNLOAD_VOICE=true
DEFAULT_VOICE="en_US-amy-medium"
CREATE_CONFIG=true
CONFIG_LOCATION="local"  # "local" or "home"

print_header() {
    echo ""
    echo -e "${BOLD}${BLUE}====================================================================${NC}"
    printf "${BOLD}${BLUE}%60s${NC}\n" "$1"
    echo -e "${BOLD}${BLUE}====================================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

print_step() {
    echo ""
    echo -e "${BOLD}${BLUE}→ $1${NC}"
}

confirm() {
    local question="$1"
    local default="$2"
    local suffix

    if [ "$default" = "true" ]; then
        suffix=" [Y/n]"
    else
        suffix=" [y/N]"
    fi

    read -r -p "${question}${suffix} " response
    if [ -z "$response" ]; then
        if [ "$default" = "true" ]; then
            return 0  # yes
        else
            return 1  # no
        fi
    fi

    case "$response" in
        [Yy][Ee][Ss]|[Yy]) return 0 ;;
        *) return 1 ;;
    esac
}

check_python() {
    print_step "Checking Python version..."

    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed or not in PATH"
        print_info "Please install Python 3.10 or newer from https://www.python.org/"
        return 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    REQUIRED_VERSION="3.10"

    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
        print_error "Python $PYTHON_VERSION detected"
        print_error "DrinkingFountain requires Python $REQUIRED_VERSION or newer"
        return 1
    fi

    print_success "Python $PYTHON_VERSION is compatible"
    return 0
}

check_uv() {
    if command -v uv &> /dev/null; then
        return 0
    else
        return 1
    fi
}

check_pip() {
    if python3 -m pip --version &> /dev/null; then
        return 0
    else
        return 1
    fi
}

check_ffmpeg() {
    if command -v ffmpeg &> /dev/null; then
        return 0
    else
        return 1
    fi
}

create_venv() {
    print_step "Creating virtual environment..."
    local venv_path="$1"

    if [ -d "$venv_path" ]; then
        print_warning "Virtual environment already exists at $venv_path"
        if confirm "Delete and recreate?" false; then
            rm -rf "$venv_path"
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi

    python3 -m venv "$venv_path"
    if [ $? -eq 0 ]; then
        print_success "Virtual environment created"
        return 0
    else
        print_error "Failed to create virtual environment"
        return 1
    fi
}

install_dependencies() {
    print_step "Installing dependencies..."
    local venv_python="$1"
    local use_uv="$2"

    if [ "$use_uv" = "true" ]; then
        print_info "Using uv for installation (fast)..."
        uv sync
    else
        print_info "Using pip for installation..."
        "$venv_python" -m pip install --upgrade pip
        "$venv_python" -m pip install -e .
    fi

    if [ $? -eq 0 ]; then
        print_success "Dependencies installed successfully"
        return 0
    else
        print_error "Failed to install dependencies"
        return 1
    fi
}

install_ffmpeg_auto() {
    print_step "Installing ffmpeg..."
    local os="$(uname -s)"

    case "$os" in
        Darwin)
            if command -v brew &> /dev/null; then
                print_info "Installing ffmpeg via Homebrew..."
                brew install ffmpeg
                if [ $? -eq 0 ]; then
                    print_success "ffmpeg installed"
                    return 0
                fi
            else
                print_warning "Homebrew not found"
            fi
            ;;
        Linux)
            if command -v apt-get &> /dev/null; then
                print_info "Installing ffmpeg via apt-get..."
                sudo apt-get update
                sudo apt-get install -y ffmpeg
                if [ $? -eq 0 ]; then
                    print_success "ffmpeg installed"
                    return 0
                fi
            elif command -v dnf &> /dev/null; then
                print_info "Installing ffmpeg via dnf..."
                sudo dnf install -y ffmpeg
                if [ $? -eq 0 ]; then
                    print_success "ffmpeg installed"
                    return 0
                fi
            elif command -v pacman &> /dev/null; then
                print_info "Installing ffmpeg via pacman..."
                sudo pacman -S --noconfirm ffmpeg
                if [ $? -eq 0 ]; then
                    print_success "ffmpeg installed"
                    return 0
                fi
            fi
            ;;
        *)
            print_warning "Automatic ffmpeg installation not supported on $os"
            ;;
    esac

    print_error "Could not automatically install ffmpeg"
    print_info "Please install manually:"
    echo "  macOS: brew install ffmpeg"
    echo "  Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "  Fedora: sudo dnf install ffmpeg"
    echo "  Arch: sudo pacman -S ffmpeg"
    return 1
}

install_simpleaudio() {
    print_step "Installing simpleaudio..."
    local venv_python="$1"

    "$venv_python" -m pip install simpleaudio
    if [ $? -eq 0 ]; then
        print_success "simpleaudio installed"
        return 0
    else
        print_warning "Failed to install simpleaudio"
        print_info "Audio playback will not be available, but file export will work"
        return 1
    fi
}

download_voice() {
    print_step "Downloading voice model: $1..."
    local venv_python="$1"
    local voice_id="$2"

    print_info "This may take a few minutes..."

    if [ -n "$VIRTUAL_ENV" ]; then
        # Already in venv, use drinkingfountain directly
        drinkingfountain voices download "$voice_id"
    else
        "$venv_python" -m drinkingfountain voices download "$voice_id"
    fi

    if [ $? -eq 0 ]; then
        print_success "Voice model '$voice_id' downloaded"
        return 0
    else
        print_error "Failed to download voice"
        print_info "You can download later with: drinkingfountain voices download $voice_id"
        return 1
    fi
}

create_config_file() {
    print_step "Creating configuration file..."
    local config_path="$1"
    local default_voice="$2"

    mkdir -p "$(dirname "$config_path")"

    cat > "$config_path" <<EOF
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
  # JOHN: $default_voice
  # SARAH: en_US-sarah-medium
  # NARRATOR: en_US-amy-medium

# Note: If you don't assign voices here, characters will be auto-assigned
# from available voices. The narrator voice (if present) is reserved.
EOF

    if [ $? -eq 0 ]; then
        print_success "Configuration file created at $config_path"
        print_info "Edit this file to customize voice assignments and settings."
        return 0
    else
        print_error "Failed to create config file"
        return 1
    fi
}

verify_installation() {
    print_step "Verifying installation..."

    local venv_python="$1"
    local drinkingfountain_cmd

    if [ -n "$VIRTUAL_ENV" ]; then
        drinkingfountain_cmd="$(dirname "$venv_python")/drinkingfountain"
    else
        drinkingfountain_cmd="drinkingfountain"
    fi

    if "$venv_python" -m drinkingfountain --version &> /dev/null; then
        local version=$("$venv_python" -m drinkingfountain --version)
        print_success "DrinkingFountain is installed and working!"
        print_info "Version: $version"
        return 0
    else
        print_error "Verification failed"
        return 1
    fi
}

main() {
    print_header "DrinkingFountain Installer"
    print_info "This installer will set up DrinkingFountain on your system."
    print_info "It will install dependencies, download a voice model, and create a config file."
    echo ""

    # Check Python
    if ! check_python; then
        print_error "Installation aborted: Python version requirement not met"
        exit 1
    fi

    # Virtual environment
    print_step "Virtual environment setup"
    if confirm "Create a virtual environment? (recommended)" true; then
        USE_VENV=true
        VENV_PATH="$PROJECT_ROOT/.venv"

        if create_venv "$VENV_PATH"; then
            PYTHON_CMD="$VENV_PATH/bin/python"
        else
            print_error "Failed to create virtual environment"
            exit 1
        fi
    else
        USE_VENV=false
        print_warning "Using system Python. Consider using a virtual environment to avoid conflicts."
        PYTHON_CMD="python3"
    fi

    # Package manager
    print_step "Checking package manager..."
    if check_uv; then
        print_info "uv is available - will use it for fast dependency resolution"
        if confirm "Use uv for installation? (recommended)" true; then
            USE_UV=true
        else
            USE_UV=false
        fi
    else
        if ! check_pip; then
            print_error "Neither uv nor pip is available. Please install pip first."
            exit 1
        fi
        USE_UV=false
        print_info "Will use pip for installation"
    fi

    # Install dependencies
    if ! install_dependencies "$PYTHON_CMD" "$USE_UV"; then
        print_error "Failed to install dependencies"
        exit 1
    fi

    # ffmpeg
    print_step "Checking for ffmpeg..."
    if check_ffmpeg; then
        print_success "ffmpeg is already installed"
    else
        print_warning "ffmpeg is not installed (needed for MP3 export)"
        if confirm "Attempt to install ffmpeg automatically?" false; then
            if install_ffmpeg_auto; then
                INSTALL_FFMPEG=true
            else
                print_warning "ffmpeg installation failed"
                print_info "You can still use WAV format. Install ffmpeg later for MP3 support."
            fi
        else
            print_info "Skipping ffmpeg installation. You can install it later."
            print_info "MP3 export will not be available until ffmpeg is installed."
        fi
    fi

    # simpleaudio
    print_step "Checking for simpleaudio (audio playback)..."
    if "$PYTHON_CMD" -c "import simpleaudio" &> /dev/null; then
        print_success "simpleaudio is already installed"
    else
        print_warning "simpleaudio is not installed (needed for direct playback)"
        if confirm "Install simpleaudio?" true; then
            if ! install_simpleaudio "$PYTHON_CMD"; then
                print_warning "simpleaudio installation failed"
                print_info "You can still export to files. Install simpleaudio later for playback."
            fi
        else
            print_info "Skipping simpleaudio installation"
        fi
    fi

    # Voice download
    print_step "Voice model setup"
    if confirm "Download a default voice model? (recommended)" true; then
        print_info "Available default options:"
        echo "  en_US-amy-medium  (American English, medium quality)"
        echo "  en_US-john-medium (American English, medium quality)"
        echo "  en_GB-james-high  (British English, high quality)"
        read -r -p "Enter voice ID [en_US-amy-medium]: " voice_input
        SELECTED_VOICE="${voice_input:-en_US-amy-medium}"

        if ! download_voice "$PYTHON_CMD" "$SELECTED_VOICE"; then
            print_warning "Voice download failed"
            print_info "You can download voices later with: drinkingfountain voices download <voice_id>"
        fi
        DEFAULT_VOICE="$SELECTED_VOICE"
    else
        print_info "Skipping voice download"
        print_info "Remember to download at least one voice before using:"
        print_info "  drinkingfountain voices download en_US-amy-medium"
        DEFAULT_VOICE=""
    fi

    # Config file
    print_step "Configuration file"
    if confirm "Create a sample configuration file?" true; then
        echo "Where should the config file be created?"
        echo "  1. Local directory (./drinkingfountain.yaml) - recommended for project-specific settings"
        echo "  2. Home directory (~/.config/drinkingfountain/config.yaml) - for global settings"
        read -r -p "Choose location [1]: " config_choice
        config_choice="${config_choice:-1}"

        if [ "$config_choice" = "2" ]; then
            CONFIG_PATH="$HOME/.config/drinkingfountain/config.yaml"
        else
            CONFIG_PATH="$PROJECT_ROOT/drinkingfountain.yaml"
        fi

        if [ -n "$DEFAULT_VOICE" ]; then
            create_config_file "$CONFIG_PATH" "$DEFAULT_VOICE"
        else
            create_config_file "$CONFIG_PATH" "en_US-amy-medium"
        fi
    else
        print_info "Skipping config file creation"
    fi

    # Verification
    print_step "Verifying installation..."
    if verify_installation "$PYTHON_CMD"; then
        print_header "Installation Complete!"
        print_success "DrinkingFountain has been successfully installed!"

        echo ""
        echo -e "${BOLD}Next steps:${NC}"
        echo "  1. If you haven't downloaded a voice, do it now:"
        echo "     drinkingfountain voices download en_US-amy-medium"
        echo "  2. Create a Fountain script (e.g., script.fountain)"
        echo "  3. Render it to audio:"
        echo "     drinkingfountain render script.fountain -o output.wav"
        echo ""
        echo "Or play directly through speakers (if simpleaudio installed):"
        echo "     drinkingfountain render script.fountain"
        echo ""
        echo -e "${BOLD}Documentation:${NC}"
        echo "  - README.md: Full documentation"
        echo "  - https://fountain.io: Fountain format spec"
        echo ""
        echo -e "${GREEN}Happy scripting! 🎭${NC}"
        echo ""
    else
        print_warning "Installation completed but verification failed"
        print_info "Try running 'drinkingfountain --help' to see if the command works"
    fi
}

# Run main function
main
