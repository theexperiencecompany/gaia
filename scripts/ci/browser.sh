#!/usr/bin/env bash
# browser.sh — the real browsers a lane drives: finding them, and serving one.
#
# Subcommands:
#   locate          Find Chrome (google-chrome on the runner image) and the Obscura
#                   binary the obscura-bin build stage exported to
#                   $RUNNER_TEMP/obscura, install the Caddy self-host ships (the
#                   proxy a user's live view goes through) and the Fortress build
#                   the gaia image pins (its opt-in Chromium, which only Fortress's
#                   own identity test launches), and publish CHROMIUM_BIN /
#                   OBSCURA_BIN / CADDY_BIN / FORTRESS_BIN to $GITHUB_ENV. Any one
#                   missing fails: the browser slice never skips a scenario.
#   chrome-host     Start a Chrome browser host (python -m app.browser_host) in the
#                   background on BROWSER_HOST_PORT with a fresh host key, publish
#                   the key and a login-encryption key to $GITHUB_ENV, and wait for
#                   its healthz. Used by the on-demand browser eval.
#   eval [ids]      Run the browser quality eval suite, all cases or the
#                   comma-separated ids given.
#
# Env contract:
#   locate        RUNNER_TEMP, GITHUB_ENV; CADDY_RELEASE_URL / CADDY_SHA512 and
#                 FORTRESS_RELEASE_URL / FORTRESS_SHA256 replace the pinned releases
#                 only for the script's own tests.
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
# The Caddy self-host runs (caddy:2.10.2-alpine in docker-compose.selfhost.yml),
# and the sha512 of its linux_amd64 release from caddy_2.10.2_checksums.txt.
CADDY_VERSION=2.10.2
CADDY_RELEASE_URL="${CADDY_RELEASE_URL:-https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz}"
CADDY_SHA512="${CADDY_SHA512:-747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546}"

# Fortress is pinned once, in the gaia image (apps/api/Dockerfile's FORTRESS_* ARGs):
# CI installs the same release, checked against the same SHA-256, that production runs.
DOCKERFILE="$REPO_ROOT/apps/api/Dockerfile"

dockerfile_arg() {
  local value
  value="$(sed -n "s/^ARG $1=//p" "$DOCKERFILE")"
  [ -n "$value" ] || ci_die "no ARG $1 in $DOCKERFILE"
  echo "$value"
}

install_fortress() {
  local version platform sha256 url
  version="$(dockerfile_arg FORTRESS_VERSION)"
  case "$(uname -m)" in
    x86_64) platform=linux-x64 sha256="$(dockerfile_arg FORTRESS_SHA256_AMD64)" ;;
    aarch64 | arm64) platform=linux-arm64 sha256="$(dockerfile_arg FORTRESS_SHA256_ARM64)" ;;
    *) ci_die "no Fortress build for $(uname -m)" ;;
  esac
  url="${FORTRESS_RELEASE_URL:-https://github.com/tiliondev/fortress/releases/download/v${version}/fortress-v${version%%.*}-${platform}.tar.gz}"
  sha256="${FORTRESS_SHA256:-$sha256}"
  local dir="${RUNNER_TEMP:?RUNNER_TEMP required}/fortress"
  local archive="$dir.tar.gz"
  mkdir -p "$dir"
  curl -fsSL -o "$archive" "$url"
  echo "$sha256  $archive" | sha256sum -c - > /dev/null || ci_die "fortress ${version} failed its checksum"
  tar -C "$dir" -xzf "$archive" --strip-components=1
  rm -f "$archive"
  echo "$dir/tilion"
}

install_caddy() {
  local dir="${RUNNER_TEMP:?RUNNER_TEMP required}/caddy"
  local archive="$dir/caddy.tar.gz"
  mkdir -p "$dir"
  curl -fsSL -o "$archive" "$CADDY_RELEASE_URL"
  echo "$CADDY_SHA512  $archive" | sha512sum -c - > /dev/null || ci_die "caddy ${CADDY_VERSION} failed its checksum"
  tar -C "$dir" -xzf "$archive" caddy
  echo "$dir/caddy"
}

cmd_locate() {
  local chrome obscura caddy fortress
  chrome="$(command -v google-chrome)" || ci_die "google-chrome is not on this runner"
  obscura="${RUNNER_TEMP:?RUNNER_TEMP required}/obscura/obscura"
  [ -x "$obscura" ] || ci_die "no Obscura binary at $obscura (the obscura-bin build stage did not export one)"
  {
    echo "CHROMIUM_BIN=$chrome"
    echo "OBSCURA_BIN=$obscura"
  } >> "${GITHUB_ENV:?GITHUB_ENV required}"
  caddy="$(install_caddy)"
  echo "CADDY_BIN=$caddy" >> "$GITHUB_ENV"
  fortress="$(install_fortress)"
  echo "FORTRESS_BIN=$fortress" >> "$GITHUB_ENV"
  ci_ok "browsers: $("$chrome" --version), Obscura at $obscura, Fortress $(dockerfile_arg FORTRESS_VERSION) at $fortress, proxy $("$caddy" version)"
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
  sed -n '2,27p' "$0" >&2
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
