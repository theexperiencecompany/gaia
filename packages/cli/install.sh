#!/bin/sh
set -e

# GAIA CLI Installer
# Usage: curl -fsSL https://heygaia.io/install.sh | sh

BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { printf "${BLUE}[info]${NC} %s\n" "$1"; }
success() { printf "${GREEN}[ok]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[warn]${NC} %s\n" "$1"; }
error() { printf "${RED}[error]${NC} %s\n" "$1"; exit 1; }

detect_os() {
  case "$(uname -s)" in
    Linux*)   echo "linux" ;;
    Darwin*)  echo "macos" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *)        echo "unknown" ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo "x64" ;;
    aarch64|arm64)  echo "arm64" ;;
    *)              echo "unknown" ;;
  esac
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

install_bun() {
  info "Installing Bun..."
  if [ "$(detect_os)" = "windows" ]; then
    error "Please install Bun manually on Windows: https://bun.sh/docs/installation"
  fi
  curl -fsSL https://bun.sh/install | bash
  export BUN_INSTALL="$HOME/.bun"
  export PATH="$BUN_INSTALL/bin:$PATH"
  if ! check_command bun; then
    error "Bun installation failed. Please install manually: https://bun.sh"
  fi
  success "Bun installed successfully"
}

main() {
  printf "\n${BOLD}${BLUE}GAIA CLI Installer${NC}\n\n"

  OS=$(detect_os)
  ARCH=$(detect_arch)
  info "Detected: $OS ($ARCH)"

  if [ "$OS" = "unknown" ]; then
    error "Unsupported operating system"
  fi

  # Check for Bun
  if check_command bun; then
    success "Bun is already installed ($(bun --version))"
  else
    warn "Bun is not installed"
    install_bun
  fi

  # Install GAIA CLI globally
  info "Installing @heygaia/cli..."
  bun install -g @heygaia/cli

  if check_command gaia; then
    success "GAIA CLI installed successfully!"
    printf "\n${BOLD}Get started:${NC}\n"
    printf "  ${GREEN}gaia init${NC}    - Set up GAIA from scratch\n"
    printf "  ${GREEN}gaia setup${NC}   - Configure an existing repo\n"
    printf "  ${GREEN}gaia status${NC}  - Check service health\n"
    printf "  ${GREEN}gaia --help${NC}  - Show all commands\n\n"
  else
    warn "Installation completed but 'gaia' command not found in PATH"
    printf "You may need to add Bun's global bin directory to your PATH:\n"
    printf "  export PATH=\"\$HOME/.bun/bin:\$PATH\"\n\n"
  fi
}

main
