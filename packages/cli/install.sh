#!/bin/sh
set -e

# GAIA CLI Installer
# Usage: curl -fsSL https://heygaia.io/install.sh | sh
# Beta:  curl -fsSL https://heygaia.io/install.sh | GAIA_CHANNEL=beta sh
# A CLI build that is not on npm (`mise run cli:try` serves one):
#        curl -fsSL http://<host>/install.sh | GAIA_CLI_TARBALL=http://<host>/heygaia-cli.tgz sh
# When the package manager's bin folder is not on your PATH (Node.js installed
# here through nvm, say), a small gaia launcher goes into GAIA_BIN_DIR
# (default /usr/local/bin, with sudo when it needs it).
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

# BEGIN GENERATED LOGO (packages/cli/scripts/bake-logo.mjs; do not edit)
LOGO_WIDTH=15
LOGO_TRUECOLOR='  \033[38;2;15;83;124m▄\033[39m\033[38;2;5;156;218m\033[48;2;15;83;124m▀▀▀▀\033[49m\033[39m\033[48;2;5;156;218m \033[49m\033[38;2;5;156;218m\033[48;2;2;189;255m▀▀▀▀\033[49m\033[39m\033[38;2;2;189;255m▄\033[39m  
  \033[38;2;15;83;124m▀▀▀▀\033[39m   \033[38;2;2;189;255m▀▀▀▀\033[39m  
\033[48;2;2;189;255m  \033[49m\033[38;2;2;189;255m▄\033[39m         \033[38;2;15;83;124m▄\033[39m\033[48;2;15;83;124m  \033[49m
\033[48;2;5;156;218m \033[49m\033[38;2;2;189;255m\033[48;2;5;156;218m▀\033[49m\033[39m\033[48;2;2;189;255m \033[49m         \033[48;2;15;83;124m \033[49m\033[38;2;15;83;124m\033[48;2;5;156;218m▀\033[49m\033[39m\033[48;2;5;156;218m \033[49m
\033[38;2;5;156;218m▀\033[39m\033[48;2;5;156;218m  \033[49m\033[48;2;15;83;124m \033[49m\033[38;2;15;83;124m▄▄\033[39m   \033[38;2;2;189;255m▄▄\033[39m\033[48;2;2;189;255m \033[49m\033[48;2;5;156;218m  \033[49m\033[38;2;5;156;218m▀\033[39m
  \033[38;2;5;156;218m▀\033[39m\033[48;2;5;156;218m \033[49m\033[48;2;15;83;124m   \033[49m \033[48;2;2;189;255m   \033[49m\033[48;2;5;156;218m \033[49m\033[38;2;5;156;218m▀\033[39m  '
LOGO_ANSI256='  \033[38;5;24m▄\033[39m\033[38;5;38m\033[48;5;24m▀▀▀▀\033[49m\033[39m\033[48;5;38m \033[49m\033[38;5;38m\033[48;5;39m▀▀▀▀\033[49m\033[39m\033[38;5;39m▄\033[39m  
  \033[38;5;24m▀▀▀▀\033[39m   \033[38;5;39m▀▀▀▀\033[39m  
\033[48;5;39m  \033[49m\033[38;5;39m▄\033[39m         \033[38;5;24m▄\033[39m\033[48;5;24m  \033[49m
\033[48;5;38m \033[49m\033[38;5;39m\033[48;5;38m▀\033[49m\033[39m\033[48;5;39m \033[49m         \033[48;5;24m \033[49m\033[38;5;24m\033[48;5;38m▀\033[49m\033[39m\033[48;5;38m \033[49m
\033[38;5;38m▀\033[39m\033[48;5;38m  \033[49m\033[48;5;24m \033[49m\033[38;5;24m▄▄\033[39m   \033[38;5;39m▄▄\033[39m\033[48;5;39m \033[49m\033[48;5;38m  \033[49m\033[38;5;38m▀\033[39m
  \033[38;5;38m▀\033[39m\033[48;5;38m \033[49m\033[48;5;24m   \033[49m \033[48;5;39m   \033[49m\033[48;5;38m \033[49m\033[38;5;38m▀\033[39m  '
LOGO_PLAIN='  ▄█████████▄  
  ▀▀▀▀   ▀▀▀▀  
██▄         ▄██
███         ███
▀███▄▄   ▄▄███▀
  ▀████ ████▀  '
# END GENERATED LOGO

LOGO_TEXT_GAP=3
HEADER_TITLE="GAIA installer"

# How the logo is painted here, the way the gaia CLI picks it: truecolor, 256
# colours or plain blocks; nothing (the one-line header) when piped, NO_COLOR,
# or a terminal too narrow for the logo beside its text.
logo_variant() {
  [ -n "$BOLD" ] || return 0
  COLS="${COLUMNS:-$(tput cols 2>/dev/null || true)}"
  case "$COLS" in
    ''|*[!0-9]*) COLS=80 ;;
  esac
  [ "$COLS" -ge $((2 + LOGO_WIDTH + LOGO_TEXT_GAP + ${#HEADER_TITLE} + 8)) ] || return 0
  case "${COLORTERM:-}" in
    truecolor|24bit) echo truecolor; return 0 ;;
  esac
  case "${TERM:-}" in
    *256color*) echo ansi256 ;;
    *) echo plain ;;
  esac
}

# The logo with the title and $1 (what is being installed) centred beside it.
print_header() {
  VARIANT=$(logo_variant)
  if [ -z "$VARIANT" ]; then
    printf "\n  ${BOLD}%s${NC}\n\n" "$HEADER_TITLE"
    return 0
  fi
  case "$VARIANT" in
    truecolor) LOGO="$LOGO_TRUECOLOR" ;;
    ansi256) LOGO="$LOGO_ANSI256" ;;
    *) LOGO="$LOGO_PLAIN" ;;
  esac
  LOGO_ROWS=$(printf '%s\n' "$LOGO" | wc -l)
  TEXT_ROW=$(( (LOGO_ROWS - 2) / 2 ))
  ROW=0
  printf '\n'
  while IFS= read -r LOGO_LINE; do
    printf "  $LOGO_LINE"
    case "$ROW" in
      "$TEXT_ROW") printf "%${LOGO_TEXT_GAP}s${BOLD}%s${NC}" "" "$HEADER_TITLE" ;;
      "$((TEXT_ROW + 1))") printf "%${LOGO_TEXT_GAP}s${DIM}%s${NC}" "" "$1" ;;
    esac
    printf '\n'
    ROW=$((ROW + 1))
  done <<EOF
$LOGO
EOF
  printf '\n'
}

# A live spinner line only where a person watches it; a pipe or log gets the ✓ lines alone.
ANIMATE=""
if [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; then
  ANIMATE="1"
fi
SPINNER_PID=""
SIGINT_EXIT_CODE=130

NVM_INSTALLER_URL="https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"
LOG_TAIL_LINES=20

# The same marks the gaia CLI uses: the mark carries the colour, not the text.
done_line() {
  stop_spinner
  printf "  ${GREEN}✓${NC} %-34s ${DIM}%s${NC}\n" "$1" "$2"
}
warn() { printf "  ${YELLOW}!${NC} %s\n" "$1"; }
error() {
  stop_spinner
  printf "  ${RED}✗${NC} %s\n" "$1"
  exit 1
}

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

# Redraw "⠋ <what is happening>  <elapsed>" in place until killed. $2 names a
# function whose output, read once a second, replaces the label: the measured
# progress (a percentage, megabytes downloaded) where the step has one.
spin() {
  trap - EXIT
  SPIN_LABEL="$1"
  SPIN_PROBE="$2"
  SPIN_TEXT="$SPIN_LABEL"
  TICK=0
  set -- ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏
  while :; do
    if [ -n "$SPIN_PROBE" ] && [ $((TICK % 10)) -eq 0 ]; then
      SPIN_TEXT=$("$SPIN_PROBE") || SPIN_TEXT=""
      [ -n "$SPIN_TEXT" ] || SPIN_TEXT="$SPIN_LABEL"
    fi
    printf "\r\033[K  ${CYAN}%s${NC} %-34s ${DIM}%s${NC}" "$1" "$SPIN_TEXT" "$(step_took)"
    FRAME="$1"
    shift
    set -- "$@" "$FRAME"
    TICK=$((TICK + 1))
    sleep 0.1
  done
}

start_spinner() {
  stop_spinner
  [ -n "$ANIMATE" ] || return 0
  printf '\033[?25l'
  spin "$1" "${2:-}" &
  SPINNER_PID=$!
}

# Erase the live line, so what prints next takes its place.
stop_spinner() {
  [ -n "$SPINNER_PID" ] || return 0
  kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf '\r\033[K\033[?25h' >&3
}

# Ctrl-C: a script's background job ignores SIGINT, so the spinner is stopped
# here and its line replaced by one that says what happened. Both write to fd 3,
# the terminal: the trap runs while the step's own output still goes to the log.
on_interrupt() {
  stop_spinner
  printf "  ${YELLOW}■${NC} Cancelled. Run the installer again to finish.\n" >&3
  exit "$SIGINT_EXIT_CODE"
}

# Run "$@" with its output in LOG_FILE under a spinner labelled $1 (probe $2,
# see spin); on failure show the log's tail and exit. Called directly, not in
# a subshell, so shell functions like nvm can change PATH.
run_step() {
  STEP="$1"
  PROBE="$2"
  shift 2
  printf "\n==> %s\n" "$STEP" >>"$LOG_FILE"
  start_spinner "$STEP" "$PROBE"
  "$@" >>"$LOG_FILE" 2>&1 || {
    STATUS=$?
    stop_spinner
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

# Where `nvm install` is, from its own output: the curl bar's percentage while
# Node downloads, then the unpacking that follows the checksum.
node_install_progress() {
  NVM_OUTPUT=$(tail -c +$((NODE_LOG_START + 1)) "$LOG_FILE" | tr '\r' '\n')
  case "$NVM_OUTPUT" in
    *"Checksums matched"*) printf 'Unpacking Node.js' ;;
    *"Downloading https://"*)
      PERCENT=$(printf '%s\n' "$NVM_OUTPUT" | grep -o '[0-9][0-9.]*%' | tail -n 1)
      printf 'Downloading Node.js%s' "${PERCENT:+ · $PERCENT}"
      ;;
  esac
}

install_node() {
  if [ "$(detect_os)" = "windows" ]; then
    error "Install Node.js from https://nodejs.org, then run this installer again."
  fi
  step_start
  run_step "Downloading the Node.js installer" "" download_and_run_nvm_installer
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  [ -z "$ANIMATE" ] || NODE_LOG_START=$(wc -c <"$LOG_FILE" | tr -d ' ')
  run_step "Finding the latest Node.js" node_install_progress nvm install --lts
  if ! check_command node; then
    error "Node.js didn't install. Install it from https://nodejs.org, then run this installer again."
  fi
  done_line "Node.js $(node --version | sed 's/^v//') installed" "$(step_took)"
}

npm_install_cli() {
  NPM_CONFIG_UPDATE_NOTIFIER=false npm install -g --ignore-scripts --no-fund --no-audit --loglevel=error "$PACKAGE"
}

# Kilobytes in npm's download cache, which every package it installs passes through.
npm_cache_kb() {
  du -sk "$NPM_CACHE_DIR" 2>/dev/null | cut -f1
}

# What npm has downloaded so far: its cache's growth since the step began.
npm_install_progress() {
  KB=$(npm_cache_kb)
  [ -n "$KB" ] || return 0
  MB=$(( (KB - NPM_CACHE_START_KB) / 1024 ))
  [ "$MB" -gt 0 ] && printf 'Installing the GAIA CLI · %s MB downloaded' "$MB"
  return 0
}

global_bin_dir() {
  case "$1" in
    npm)  printf '%s/bin\n' "$(npm config get prefix)" ;;
    pnpm) pnpm bin -g ;;
    bun)  bun pm bin -g ;;
  esac
}

LAUNCHER_MARK="# Written by the GAIA installer"

is_launcher() {
  grep -q "^$LAUNCHER_MARK" "$1" 2>/dev/null
}

# True when the folder $1 is one of the PATH entries in $2.
dir_on_path() {
  case ":$2:" in
    *":$1:"*) return 0 ;;
  esac
  return 1
}

# $1 in single quotes, for a line of sh.
sh_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# Run "$@" as root only when LAUNCHER_DIR is not this user's to write.
as_launcher_owner() {
  if [ -d "$LAUNCHER_DIR" ] && [ -w "$LAUNCHER_DIR" ]; then
    "$@"
  else
    sudo -p "  [sudo] password for %u, to add gaia to $LAUNCHER_DIR: " "$@"
  fi
}

# The launcher runs GAIA_BIN with the node it was installed with, so a later
# nvm use, a new default Node.js or an unloaded nvm never loses it.
launcher_script() {
  NODE_DIR=""
  if check_command node; then
    NODE_DIR=$(command -v node)
    NODE_DIR=${NODE_DIR%/*}
  fi
  printf '#!/bin/sh\n%s (https://heygaia.io/install.sh): runs the GAIA CLI with its own Node.js.\n' "$LAUNCHER_MARK"
  printf 'GAIA_CLI=%s\n' "$(sh_quote "$GAIA_BIN")"
  printf '[ -x "$GAIA_CLI" ] || { echo "gaia: the GAIA CLI is no longer at $GAIA_CLI. Install it again: curl -fsSL https://heygaia.io/install.sh | sh" >&2; exit 127; }\n'
  if [ -n "$NODE_DIR" ]; then
    printf 'PATH=%s:"$PATH" exec "$GAIA_CLI" "$@"\n' "$(sh_quote "$NODE_DIR")"
  else
    printf 'exec "$GAIA_CLI" "$@"\n'
  fi
}

# Put gaia where the shell that ran this installer, and every later one, finds
# it. Returns non-zero when LAUNCHER_DIR is not on that PATH or can't be written.
install_launcher() {
  dir_on_path "$LAUNCHER_DIR" "$ORIGINAL_PATH" || return 1
  if ! { [ -d "$LAUNCHER_DIR" ] && [ -w "$LAUNCHER_DIR" ]; }; then
    check_command sudo || return 1
  fi
  launcher_script | as_launcher_owner sh -c \
    'mkdir -p "$1" && rm -f "$1/gaia" && cat >"$1/gaia" && chmod 755 "$1/gaia"' sh "$LAUNCHER_DIR"
}

# Offer to run the first command right away when there is a person at a terminal to
# answer; the installer already knows where gaia is, so no PATH step is needed.
offer_setup() {
  GAIA_BIN="$1"
  [ -t 1 ] || return 0
  # Not ':': a failed redirection on a special builtin exits dash outright.
  { true </dev/tty; } 2>/dev/null || return 0
  printf "\n  Set up GAIA now? [Y/n] "
  read -r ANSWER </dev/tty || return 0
  case "$ANSWER" in
    # The answered question and the blank line above it make way for gaia's own screen.
    ""|y|Y|yes|YES)
      printf '\033[1A\033[2K\033[1A\033[2K\r'
      exec "$GAIA_BIN" "$FIRST_COMMAND" </dev/tty
      ;;
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
  # The PATH of the shell that ran this, before nvm adds to it.
  ORIGINAL_PATH="$PATH"
  LAUNCHER_DIR="${GAIA_BIN_DIR:-/usr/local/bin}"
  exec 3>&1
  trap on_interrupt INT
  trap stop_spinner EXIT
  OS=$(detect_os)
  if [ "$OS" = "unknown" ]; then
    error "This installer supports Linux and macOS ($(uname -s) isn't one of them)."
  fi

  # The npm dist-tag to install: latest (default) or beta.
  CHANNEL="${GAIA_CHANNEL:-latest}"
  case "$CHANNEL" in
    latest|beta) ;;
    *) error "GAIA_CHANNEL must be 'latest' or 'beta', got '$CHANNEL'" ;;
  esac
  PACKAGE="@heygaia/cli@$CHANNEL"
  if [ -n "${GAIA_CLI_TARBALL:-}" ]; then
    print_header "custom build"
  else
    print_header "$CHANNEL"
  fi
  # An unreleased build instead of npm's: said out loud, never silently.
  if [ -n "${GAIA_CLI_TARBALL:-}" ]; then
    case "$GAIA_CLI_TARBALL" in
      http://*.tgz|https://*.tgz|/*.tgz) ;;
      *) error "GAIA_CLI_TARBALL must be an http(s) URL or absolute path ending in .tgz, got '$GAIA_CLI_TARBALL'" ;;
    esac
    PACKAGE="$GAIA_CLI_TARBALL"
    warn "Installing the GAIA CLI from $GAIA_CLI_TARBALL (GAIA_CLI_TARBALL), not from npm"
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
    npm)
      if [ -n "$ANIMATE" ]; then
        NPM_CACHE_DIR="$(npm config get cache)/_cacache"
        NPM_CACHE_START_KB=$(npm_cache_kb)
        NPM_CACHE_START_KB=${NPM_CACHE_START_KB:-0}
      fi
      run_step "Installing the GAIA CLI" npm_install_progress npm_install_cli
      ;;
    pnpm) run_step "Installing the GAIA CLI" "" pnpm add -g "$PACKAGE" ;;
    bun)  run_step "Installing the GAIA CLI" "" bun install -g --ignore-scripts "$PACKAGE" ;;
  esac
  rm -f "$LOG_FILE"

  # An earlier run's launcher points at that run's install, not this one.
  if check_command gaia && ! is_launcher "$(command -v gaia)"; then
    GAIA_BIN=$(command -v gaia)
  else
    BIN_DIR=$(global_bin_dir "$PKG_MGR")
    GAIA_BIN="$BIN_DIR/gaia"
    [ -x "$GAIA_BIN" ] || error "$PKG_MGR installed @heygaia/cli, but $GAIA_BIN doesn't exist."
  fi
  done_line "GAIA CLI $("$GAIA_BIN" --version 2>/dev/null) installed" "$(step_took)"

  # CLIs before 0.7.0 have no `up`; they start with `init`. Read the command list:
  # an unknown command's `--help` still exits 0.
  FIRST_COMMAND="init"
  "$GAIA_BIN" --help 2>/dev/null | grep -Eq '^[[:space:]]+up([[:space:]]|$)' && FIRST_COMMAND="up"

  # The shell that piped this in finds gaia already, or through the launcher.
  if dir_on_path "${GAIA_BIN%/*}" "$ORIGINAL_PATH" || install_launcher; then
    offer_setup "$GAIA_BIN"
    next_step "gaia $FIRST_COMMAND" ""
    return
  fi
  # nvm only changed this installer's PATH, never the shell that piped it in.
  if [ "$NODE_INSTALLED_VIA_NVM" = "1" ]; then
    offer_setup "$GAIA_BIN"
    next_step ". \"$NVM_DIR/nvm.sh\" && gaia $FIRST_COMMAND" "(this terminal needs nvm loaded first; new terminals find gaia on their own)"
    return
  fi
  offer_setup "$GAIA_BIN"
  next_step "export PATH=\"${GAIA_BIN%/*}:\$PATH\" && gaia $FIRST_COMMAND" "(to keep it, add that export line to ~/.bashrc or ~/.zshrc)"
}

main
