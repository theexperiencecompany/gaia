#!/usr/bin/env bash
# start-embedding-sidecar.sh — run ONE embedding sidecar for the pytest run.
#
# The memory suite embeds and reranks through app.memory.embeddings, which
# uses a shared HTTP sidecar whenever MEMORY_EMBEDDING_SIDECAR_URL is set and
# loads the ONNX models in-process otherwise. In-process, every pytest-xdist
# worker that touches a memory test loads ~1.8 GB of weights (measured: 2.2 to
# 2.6 GB RSS per worker, 16 workers ≈ 40 GB) and the loads serialize behind a
# file lock. One sidecar loads them once; workers stay ~1 GB and never wait.
#
# Port is offset by RUNNER_INDEX like the service containers, in a range that
# cannot collide with them (chroma at index 2 would otherwise land on the
# sidecar's default 8200). The URL is published to $GITHUB_ENV and to the
# services env file so the test lane and the local profiling harness share it.
set -euo pipefail

RUNNER_INDEX="${RUNNER_INDEX:-0}"
PORT=$((18200 + RUNNER_INDEX * 100))
URL="http://127.0.0.1:${PORT}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="${GAIA_SIDECAR_LOG:-/tmp/gaia-embedding-sidecar-${RUNNER_INDEX}.log}"
PIDFILE="/tmp/gaia-embedding-sidecar-${RUNNER_INDEX}.pid"

# A sidecar left behind by an interrupted job would hold the port.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true; sleep 1
fi

cd "$REPO_ROOT/apps/api"
# --no-sync: the environment is already synced by the caller; this must not
# touch the network. The model cache dir is inherited from the environment.
nohup uv run --frozen --no-sync uvicorn app.services.embedding_sidecar.server:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning > "$LOG" 2>&1 < /dev/null &
echo $! > "$PIDFILE"

# Model load is the startup cost (~5-20s from a warm disk cache).
deadline=$((SECONDS + 180))
until curl -sf "${URL}/health" > /dev/null 2>&1; do
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "::error::embedding sidecar exited during startup"; tail -30 "$LOG"; exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "::error::embedding sidecar not healthy after 180s"; tail -30 "$LOG"; exit 1
  fi
  sleep 1
done
echo "embedding sidecar ready at ${URL} (pid $(cat "$PIDFILE"), $((SECONDS))s)"

if [ -n "${GITHUB_ENV:-}" ]; then
  echo "MEMORY_EMBEDDING_SIDECAR_URL=${URL}" >> "$GITHUB_ENV"
fi
SERVICES_ENV_FILE="${GAIA_TEST_SERVICES_ENV:-/tmp/gaia-test-services-${RUNNER_INDEX}.env}"
if [ -f "$SERVICES_ENV_FILE" ]; then
  grep -v '^MEMORY_EMBEDDING_SIDECAR_URL=' "$SERVICES_ENV_FILE" > "$SERVICES_ENV_FILE.tmp" || true
  echo "MEMORY_EMBEDDING_SIDECAR_URL=${URL}" >> "$SERVICES_ENV_FILE.tmp"
  mv "$SERVICES_ENV_FILE.tmp" "$SERVICES_ENV_FILE"
fi
