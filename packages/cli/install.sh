#!/bin/sh
set -e

# GAIA CLI Installer
# Usage: curl -fsSL https://heygaia.io/install.sh | sh
#
# NOTE: Do not rename this file. The web app serves it at heygaia.io/install.sh
# by fetching it from GitHub using this exact path: packages/cli/install.sh

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

install_node() {
  info "Installing Node.js via nvm..."
  if [ "$(detect_os)" = "windows" ]; then
    error "Please install Node.js manually on Windows: https://nodejs.org"
  fi
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  nvm install --lts
  if ! check_command node; then
    error "Node.js installation failed. Please install manually: https://nodejs.org"
  fi
  success "Node.js $(node --version) installed successfully"
}

show_path_help() {
  PKG="$1"
  case "$PKG" in
    npm)
      BIN_DIR="$(npm config get prefix)/bin"
      printf "  Run: ${BOLD}export PATH=\"%s:\$PATH\"${NC}\n" "$BIN_DIR"
      printf "  Or add it to your shell profile (~/.bashrc, ~/.zshrc, etc.)\n"
      ;;
    pnpm)
      BIN_DIR="$(pnpm bin -g 2>/dev/null || echo '$HOME/.local/share/pnpm')"
      printf "  Run: ${BOLD}export PATH=\"%s:\$PATH\"${NC}\n" "$BIN_DIR"
      printf "  Or run: ${BOLD}pnpm setup${NC} to configure PATH automatically\n"
      ;;
    bun)
      printf "  Run: ${BOLD}export PATH=\"\$HOME/.bun/bin:\$PATH\"${NC}\n"
      printf "  Or add it to your shell profile (~/.bashrc, ~/.zshrc, etc.)\n"
      ;;
  esac
}

main() {
  printf "\n${BOLD}${BLUE}GAIA CLI Installer${NC}\n\n"

  OS=$(detect_os)
  ARCH=$(detect_arch)
  info "Detected: $OS ($ARCH)"

  if [ "$OS" = "unknown" ]; then
    error "Unsupported operating system"
  fi

  # Determine package manager: prefer npm, then pnpm, then bun
  PKG_MGR=""

  if check_command npm; then
    success "npm is already installed ($(npm --version))"
    PKG_MGR="npm"
  elif check_command pnpm; then
    success "pnpm is already installed ($(pnpm --version))"
    PKG_MGR="pnpm"
  elif check_command bun; then
    success "Bun is already installed ($(bun --version))"
    PKG_MGR="bun"
  else
    warn "No supported package manager found (npm, pnpm, or bun)"
    install_node
    PKG_MGR="npm"
  fi

  # Install GAIA CLI globally
  info "Installing @heygaia/cli via $PKG_MGR..."
  case "$PKG_MGR" in
    npm)  npm install -g @heygaia/cli ;;
    pnpm) pnpm add -g @heygaia/cli ;;
    bun)  bun install -g @heygaia/cli ;;
  esac

  if check_command gaia; then
    success "GAIA CLI installed successfully!"
    printf "\n${BOLD}Get started:${NC}\n"
    printf "  ${GREEN}gaia init${NC}    - Set up GAIA from scratch\n"
    printf "  ${GREEN}gaia setup${NC}   - Configure an existing repo\n"
    printf "  ${GREEN}gaia status${NC}  - Check service health\n"
    printf "  ${GREEN}gaia --help${NC}  - Show all commands\n\n"
  else
    warn "Installation completed but 'gaia' command not found in PATH"
    show_path_help "$PKG_MGR"
    printf "\n"
  fi
}

main
