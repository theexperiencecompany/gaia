#!/usr/bin/env bash
# browser.sh — the real browsers a lane drives: finding them, and serving one.
#
# Subcommands:
#   locate          Find Chrome (google-chrome on the runner image) and the Obscura
#                   binary the obscura-bin build stage exported to
#                   $RUNNER_TEMP/obscura, and publish CHROMIUM_BIN / OBSCURA_BIN to
#                   $GITHUB_ENV. Either one missing fails: the browser slice
#                   never skips a scenario for want of an engine.
#   chrome-host     Start a Chrome browser host (python -m app.browser_host) in the
#                   background on BROWSER_HOST_PORT with a fresh host key, publish
#                   the key and a login-encryption key to $GITHUB_ENV, and wait for
#                   its healthz. Used by the on-demand browser eval.
#   eval [ids]      Run the browser quality eval suite, all cases or the
#                   comma-separated ids given.
#
# Env contract:
#   locate        RUNNER_TEMP, GITHUB_ENV.
#   chrome-host   RUNNER_TEMP, GITHUB_ENV, BROWSER_HOST_PORT; CHROMIUM_BIN, else google-chrome.
#   eval          what the suite reads (BROWSER_HOST_URL, OPENROUTER_API_KEY, ...), and
#                 OPENROUTER_MODEL: the model the browser agent runs on, which the
#                 eval records as the run's model (the product, not the eval, picks it).
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# How long a host gets to launch its engine and answer healthz.
HOST_READY_SECONDS=120

cmd_locate() {
  local chrome obscura
  chrome="$(command -v google-chrome)" || ci_die "google-chrome is not on this runner"
  obscura="${RUNNER_TEMP:?RUNNER_TEMP required}/obscura/obscura"
  [ -x "$obscura" ] || ci_die "no Obscura binary at $obscura (the obscura-bin build stage did not export one)"
  {
    echo "CHROMIUM_BIN=$chrome"
    echo "OBSCURA_BIN=$obscura"
  } >> "${GITHUB_ENV:?GITHUB_ENV required}"
  ci_ok "browsers: $("$chrome" --version), Obscura at $obscura"
}

cmd_chrome_host() {
  local port="${BROWSER_HOST_PORT:?BROWSER_HOST_PORT required}"
  local chrome key log
  chrome="${CHROMIUM_BIN:-$(command -v google-chrome)}" || ci_die "google-chrome is not on this runner"
  key="$(openssl rand -hex 16)"
  log="${RUNNER_TEMP:?RUNNER_TEMP required}/browser-host.log"
  {
    echo "BROWSER_HOST_KEY=$key"
    echo "BROWSER_STATE_ENCRYPTION_KEY=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  } >> "${GITHUB_ENV:?GITHUB_ENV required}"
  (
    cd "$REPO_ROOT/apps/api"
    BROWSER_HOST_KEY="$key" BROWSER_ENGINE=chromium CHROMIUM_BIN="$chrome" \
      nohup uv run --frozen --group backend python -m app.browser_host > "$log" 2>&1 &
  )
  local waited=0
  until curl -fsS -H "X-Host-Key: $key" "http://127.0.0.1:${port}/healthz" > /dev/null 2>&1; do
    waited=$((waited + 1))
    if [ "$waited" -ge "$HOST_READY_SECONDS" ]; then
      cat "$log" >&2
      ci_die "the Chrome host never answered healthz on port $port within ${HOST_READY_SECONDS}s"
    fi
    sleep 1
  done
  ci_ok "Chrome host: serving on port $port (log $log)"
}

cmd_eval() {
  local only="${1:-}"
  : "${OPENROUTER_MODEL:?OPENROUTER_MODEL required: the model the browser agent runs on, as the run records it}"
  local args=(run --suite browser --providers openrouter)
  [ -z "$only" ] || args+=(--only "$only")
  cd "$REPO_ROOT/apps/api"
  uv run --frozen --group backend python -m scripts.evals "${args[@]}"
}

usage() {
  sed -n '2,20p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    locate) cmd_locate "$@" ;;
    chrome-host) cmd_chrome_host "$@" ;;
    eval) cmd_eval "$@" ;;
    *)
      echo "browser.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
