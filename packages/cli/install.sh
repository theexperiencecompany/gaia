#!/bin/sh
set -e

# GAIA CLI Installer
# Usage: curl -fsSL https://heygaia.io/install.sh | sh
#
# NOTE: Do not rename this file. The web app serves it at heygaia.io/install.sh
# by fetching it from GitHub using this exact path: packages/cli/install.sh

# Colour only on a terminal that wants it.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  BOLD='\033[1m'
  DIM='\033[2m'
  GREEN='\033[0;32m'
  CYAN='\033[0;36m'
  YELLOW='\033[0;33m'
  RED='\033[0;31m'
  NC='\033[0m'
else
  BOLD='' DIM='' GREEN='' CYAN='' YELLOW='' RED='' NC=''
fi

NVM_INSTALLER_URL="https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"
LOG_TAIL_LINES=20

# The same marks the gaia CLI uses: the mark carries the colour, not the text.
done_line() { printf "  ${GREEN}✓${NC} %-34s ${DIM}%s${NC}\n" "$1" "$2"; }
warn() { printf "  ${YELLOW}!${NC} %s\n" "$1"; }
error() { printf "  ${RED}✗${NC} %s\n" "$1"; exit 1; }

detect_os() {
  case "$(uname -s)" in
    Linux*)   echo "linux" ;;
    Darwin*)  echo "macos" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *)        echo "unknown" ;;
  esac
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

STEP_STARTED=0
step_start() { STEP_STARTED=$(date +%s); }
# 12s, 1m 04s: how long the current step took.
step_took() {
  ELAPSED=$(( $(date +%s) - STEP_STARTED ))
  if [ "$ELAPSED" -lt 60 ]; then
    printf '%ss' "$ELAPSED"
  else
    printf '%sm %02ds' $(( ELAPSED / 60 )) $(( ELAPSED % 60 ))
  fi
}

# Run "$@" with its output in LOG_FILE; on failure show the log's tail and exit.
# Called directly (not in a subshell) so shell functions like nvm can change PATH.
run_quiet() {
  STEP="$1"
  shift
  printf "\n==> %s\n" "$STEP" >>"$LOG_FILE"
  "$@" >>"$LOG_FILE" 2>&1 || {
    STATUS=$?
    printf "  ${RED}✗${NC} %s failed (exit %s). Its last %s lines:\n" "$STEP" "$STATUS" "$LOG_TAIL_LINES"
    tail -n "$LOG_TAIL_LINES" "$LOG_FILE"
    printf "  Full log: %s\n" "$LOG_FILE"
    exit 1
  }
}

download_and_run_nvm_installer() {
  NVM_INSTALLER=$(curl --proto '=https' --tlsv1.2 -fsSL "$NVM_INSTALLER_URL") || return
  printf '%s\n' "$NVM_INSTALLER" | bash
}

install_node() {
  if [ "$(detect_os)" = "windows" ]; then
    error "Install Node.js from https://nodejs.org, then run this installer again."
  fi
  step_start
  run_quiet "Installing nvm" download_and_run_nvm_installer
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  run_quiet "Installing Node.js LTS via nvm" nvm install --lts
  if ! check_command node; then
    error "Node.js didn't install. Install it from https://nodejs.org, then run this installer again."
  fi
  done_line "Node.js $(node --version | sed 's/^v//') installed" "$(step_took)"
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

# Offer to run `gaia up` right away when there is a person at a terminal to
# answer; the installer already knows where gaia is, so no PATH step is needed.
offer_setup() {
  GAIA_BIN="$1"
  [ -t 1 ] || return 0
  { : </dev/tty; } 2>/dev/null || return 0
  printf "\n  Set up GAIA now? [Y/n] "
  read -r ANSWER </dev/tty || return 0
  case "$ANSWER" in
    ""|y|Y|yes|YES) exec "$GAIA_BIN" up </dev/tty ;;
  esac
}

# One next step, as a command that works in this terminal.
next_step() {
  RUN_NOW="$1"
  LATER="$2"
  printf "\n  Next, run:  ${BOLD}${CYAN}%s${NC}\n" "$RUN_NOW"
  [ -n "$LATER" ] && printf "  ${DIM}%s${NC}\n" "$LATER"
  printf "\n"
}

main() {
  printf "\n  ${BOLD}GAIA installer${NC}\n\n"

  OS=$(detect_os)
  if [ "$OS" = "unknown" ]; then
    error "This installer supports Linux and macOS ($(uname -s) isn't one of them)."
  fi

  LOG_FILE=$(mktemp "${TMPDIR:-/tmp}/gaia-install.XXXXXX")

  # Determine package manager: prefer npm, then pnpm, then bun
  PKG_MGR=""
  NODE_INSTALLED_VIA_NVM=""

  if check_command npm; then
    PKG_MGR="npm"
  elif check_command pnpm; then
    PKG_MGR="pnpm"
  elif check_command bun; then
    PKG_MGR="bun"
  else
    install_node
    NODE_INSTALLED_VIA_NVM="1"
    PKG_MGR="npm"
  fi

  step_start
  case "$PKG_MGR" in
    npm)  run_quiet "npm install -g @heygaia/cli" npm_install_cli ;;
    pnpm) run_quiet "pnpm add -g @heygaia/cli" pnpm add -g @heygaia/cli ;;
    bun)  run_quiet "bun install -g @heygaia/cli" bun install -g --ignore-scripts @heygaia/cli ;;
  esac
  rm -f "$LOG_FILE"

  if check_command gaia; then
    GAIA_BIN=$(command -v gaia)
  else
    BIN_DIR=$(global_bin_dir "$PKG_MGR")
    GAIA_BIN="$BIN_DIR/gaia"
    [ -x "$GAIA_BIN" ] || error "$PKG_MGR installed @heygaia/cli, but $GAIA_BIN doesn't exist."
  fi
  done_line "GAIA CLI $("$GAIA_BIN" --version 2>/dev/null) installed" "$(step_took)"

  # nvm only changed this installer's PATH, never the shell that piped it in.
  if [ "$NODE_INSTALLED_VIA_NVM" = "1" ]; then
    offer_setup "$GAIA_BIN"
    next_step ". \"$NVM_DIR/nvm.sh\" && gaia up" "(this terminal needs nvm loaded first; new terminals find gaia on their own)"
    return
  fi
  if [ -n "${BIN_DIR:-}" ]; then
    offer_setup "$GAIA_BIN"
    next_step "export PATH=\"$BIN_DIR:\$PATH\" && gaia up" "(to keep it, add that export line to ~/.bashrc or ~/.zshrc)"
    return
  fi
  offer_setup "$GAIA_BIN"
  next_step "gaia up" ""
}

main
