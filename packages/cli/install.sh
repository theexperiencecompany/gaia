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

NVM_INSTALLER_URL="https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"
LOG_TAIL_LINES=20

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

os_label() {
  case "$1" in
    linux)   echo "Linux" ;;
    macos)   echo "macOS" ;;
    windows) echo "Windows" ;;
    *)       echo "$1" ;;
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

# Run "$@" with its output in LOG_FILE; on failure show the log's tail and exit.
# Called directly (not in a subshell) so shell functions like nvm can change PATH.
run_quiet() {
  STEP="$1"
  shift
  printf "\n==> %s\n" "$STEP" >>"$LOG_FILE"
  "$@" >>"$LOG_FILE" 2>&1 || {
    STATUS=$?
    printf "${RED}[error]${NC} %s failed (exit %s). Last %s lines of output:\n" "$STEP" "$STATUS" "$LOG_TAIL_LINES"
    tail -n "$LOG_TAIL_LINES" "$LOG_FILE"
    printf "Full log: %s\n" "$LOG_FILE"
    exit 1
  }
}

download_and_run_nvm_installer() {
  NVM_INSTALLER=$(curl --proto '=https' --tlsv1.2 -fsSL "$NVM_INSTALLER_URL") || return
  printf '%s\n' "$NVM_INSTALLER" | bash
}

install_node() {
  if [ "$(detect_os)" = "windows" ]; then
    error "Please install Node.js manually on Windows: https://nodejs.org"
  fi
  run_quiet "Installing nvm" download_and_run_nvm_installer
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  run_quiet "Installing Node.js LTS via nvm" nvm install --lts
  if ! check_command node; then
    error "Node.js installation failed. Please install manually: https://nodejs.org"
  fi
  success "Node.js $(node --version) installed"
}

npm_install_cli() {
  NPM_CONFIG_UPDATE_NOTIFIER=false npm install -g --ignore-scripts --no-fund --no-audit --loglevel=error @heygaia/cli
}

global_bin_dir() {
  case "$1" in
    npm)  printf '%s/bin\n' "$(npm config get prefix)" ;;
    pnpm) pnpm bin -g ;;
    bun)  bun pm bin -g ;;
  esac
}

# The user's shell cannot run a bare `gaia` yet: print the one command that
# works in it now, then how later shells find gaia. A full path to gaia is not
# enough under nvm: its shebang needs node on PATH too.
show_not_on_path_help() {
  RUN_NOW="$1"
  LATER="$2"
  printf "\n${BOLD}Get started${NC} (this terminal cannot find gaia yet, so load it first):\n"
  printf "  ${GREEN}%s${NC}\n\n" "$RUN_NOW"
  printf "%s\n\n" "$LATER"
}

main() {
  printf "\n${BOLD}${BLUE}GAIA CLI Installer${NC}\n\n"

  OS=$(detect_os)
  ARCH=$(detect_arch)
  info "Detected: $(os_label "$OS") ($ARCH)"

  if [ "$OS" = "unknown" ]; then
    error "Unsupported operating system"
  fi

  LOG_FILE=$(mktemp "${TMPDIR:-/tmp}/gaia-install.XXXXXX")

  # Determine package manager: prefer npm, then pnpm, then bun
  PKG_MGR=""
  NODE_INSTALLED_VIA_NVM=""

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
    info "No Node.js package manager yet (npm, pnpm, or bun), so installing Node.js via nvm..."
    install_node
    NODE_INSTALLED_VIA_NVM="1"
    PKG_MGR="npm"
  fi

  info "Installing @heygaia/cli via $PKG_MGR..."
  case "$PKG_MGR" in
    npm)  run_quiet "npm install -g @heygaia/cli" npm_install_cli ;;
    pnpm) run_quiet "pnpm add -g @heygaia/cli" pnpm add -g @heygaia/cli ;;
    bun)  run_quiet "bun install -g @heygaia/cli" bun install -g --ignore-scripts @heygaia/cli ;;
  esac
  rm -f "$LOG_FILE"
  success "GAIA CLI installed"

  # nvm only changed this installer's PATH, never the shell that piped it in.
  if [ "$NODE_INSTALLED_VIA_NVM" = "1" ]; then
    check_command gaia || error "nvm's npm installed @heygaia/cli but no 'gaia' binary is on nvm's PATH"
    show_not_on_path_help ". \"$NVM_DIR/nvm.sh\" && gaia up" "New terminals find gaia on their own."
    return
  fi

  if ! check_command gaia; then
    BIN_DIR=$(global_bin_dir "$PKG_MGR")
    [ -x "$BIN_DIR/gaia" ] || error "$PKG_MGR installed @heygaia/cli but $BIN_DIR/gaia does not exist"
    show_not_on_path_help "export PATH=\"$BIN_DIR:\$PATH\" && gaia up" "To keep it, add that export line to ~/.bashrc or ~/.zshrc."
    return
  fi

  printf "\n${BOLD}Get started:${NC}\n"
  printf "  ${GREEN}gaia up${NC}      - Set up and start GAIA\n"
  printf "  ${GREEN}gaia status${NC}  - Check service health\n"
  printf "  ${GREEN}gaia --help${NC}  - Show all commands\n\n"
}

main
