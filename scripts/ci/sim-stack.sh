#!/usr/bin/env bash
# sim-stack.sh — the sim stack a browser e2e lane boots and drives: the API,
# the ARQ worker and the web dev server against the scripted LLM stub, with the
# dev auth bypass on (what `mise dev --sim` plus `nx worker api` run locally).
#
# Subcommands:
#   up    Put mongosh on PATH (the screen fixtures write Mongo through it),
#         start the stub, API, worker and web, wait until each answers, and
#         publish the endpoints the Playwright harness reads to $GITHUB_ENV.
#
# Env contract:
#   up    OUT_DIR (required: each process logs to <name>.log there),
#         MONGO_DB / MONGO_DB_NAME and the other service URLs
#         (test-services.sh prepare), GITHUB_ENV, GITHUB_PATH, RUNNER_TEMP,
#         BOOT_TIMEOUT_SECONDS (default 600: a cold boot indexes the tool
#         store in Chroma, which has taken over 180s).
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

API_PORT=8000
WEB_PORT=3000
LLM_STUB_PORT=9797
DEV_USER="dev@gaia.local"
MONGOSH_VERSION="2.14.2"
MONGOSH_SHA256="1523e16da7c6902333b681bf65d83bbef59bff558c46ac5636371d13beb4de53"

_install_mongosh() {
  if command -v mongosh > /dev/null; then
    ci_ok "mongosh: $(mongosh --version) already on PATH"
    return
  fi
  : "${RUNNER_TEMP:?RUNNER_TEMP is required}"
  : "${GITHUB_PATH:?GITHUB_PATH is required}"
  local name="mongosh-${MONGOSH_VERSION}-linux-x64"
  local tarball="$RUNNER_TEMP/$name.tgz"
  curl -fsSL -o "$tarball" \
    "https://github.com/mongodb-js/mongosh/releases/download/v${MONGOSH_VERSION}/${name}.tgz"
  echo "${MONGOSH_SHA256}  $tarball" | sha256sum -c -
  tar -C "$RUNNER_TEMP" -xzf "$tarball"
  echo "$RUNNER_TEMP/$name/bin" >> "$GITHUB_PATH"
  ci_ok "mongosh: $MONGOSH_VERSION installed"
}

# Starts one process in the background, logging to $OUT_DIR/<name>.log; prints its pid.
_start() {
  local name="$1" dir="$2"
  shift 2
  (cd "$dir" && exec nohup "$@" > "$OUT_DIR/$name.log" 2>&1 < /dev/null) &
  echo "$!"
}

# Waits until a URL answers 200 while its process lives.
_await() {
  local name="$1" pid="$2" url="$3" deadline=$((SECONDS + ${BOOT_TIMEOUT_SECONDS:-600}))
  until curl -fsS -o /dev/null "$url"; do
    kill -0 "$pid" 2> /dev/null || ci_die "$name exited while starting (see $name.log)"
    ((SECONDS < deadline)) || ci_die "$name did not answer $url within ${BOOT_TIMEOUT_SECONDS:-600}s (see $name.log)"
    sleep 2
  done
  ci_ok "$name: answering on $url after ${SECONDS}s"
}

cmd_up() {
  : "${OUT_DIR:?OUT_DIR is required}"
  : "${MONGO_DB:?MONGO_DB is required (test-services.sh prepare)}"
  : "${GITHUB_ENV:?GITHUB_ENV is required}"
  mkdir -p "$OUT_DIR"
  _install_mongosh

  # The app reads its database from MONGO_DB_NAME, not the URI's path.
  local mongo_base="${MONGO_DB%%\?*}"
  local e2e_mongo_uri="${mongo_base%/*}/${MONGO_DB_NAME:-GAIA}?authSource=admin"

  # The sim profile: development (the only ENV that admits the bypass and the
  # stub), every request as the dev user, every model call to the stub.
  export ENV=development
  export DEV_AUTH_BYPASS_EMAIL="$DEV_USER"
  export GAIA_SIM_MODE=1
  export OPENROUTER_BASE_URL="http://localhost:$LLM_STUB_PORT/api/v1"
  export NEXT_PUBLIC_API_BASE_URL="http://localhost:$API_PORT/api/v1/"
  export FRONTEND_URL="http://localhost:$WEB_PORT"
  export LLM_STUB_PORT WEB_PORT API_PORT

  local stub api worker web
  stub=$(_start llm-stub "$REPO_ROOT" uv run tools/llm-stub/server.py)
  _await llm-stub "$stub" "http://localhost:$LLM_STUB_PORT/health"
  api=$(_start api "$REPO_ROOT/apps/api" uv run --frozen --no-sync \
    uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --log-level info --no-access-log)
  worker=$(_start worker "$REPO_ROOT/apps/api" uv run --frozen --no-sync \
    arq app.worker.WorkerSettings --custom-log-dict app.workers.config.log_config.ARQ_LOG_CONFIG)
  web=$(_start web "$REPO_ROOT/apps/web" pnpm run dev)
  _await api "$api" "http://localhost:$API_PORT/health"
  kill -0 "$worker" 2> /dev/null || ci_die "the ARQ worker exited while starting (see worker.log)"
  _await web "$web" "http://localhost:$WEB_PORT/"

  {
    echo "API_PORT=$API_PORT"
    echo "WEB_PORT=$WEB_PORT"
    echo "DEV_USER=$DEV_USER"
    echo "E2E_MONGO_URI=$e2e_mongo_uri"
  } >> "$GITHUB_ENV"
  ci_ok "sim stack: web http://localhost:$WEB_PORT, API http://localhost:$API_PORT"
}

usage() {
  echo "Usage: sim-stack.sh up" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    up) cmd_up "$@" ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
