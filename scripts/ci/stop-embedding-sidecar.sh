#!/usr/bin/env bash
# stop-embedding-sidecar.sh — stop the sidecar started by start-embedding-sidecar.sh.
# Never fails the caller: it runs in teardown positions.
set -uo pipefail
RUNNER_INDEX="${RUNNER_INDEX:-0}"
PIDFILE="/tmp/gaia-embedding-sidecar-${RUNNER_INDEX}.pid"
# Self-hosted runners keep the sidecar warm for the next job on this runner
# (start-embedding-sidecar.sh reuses it while its stamp matches). STOP_SIDECAR=1
# forces the old behaviour.
if [ "${RUNNER_ENVIRONMENT:-}" = "self-hosted" ] && [ "${STOP_SIDECAR:-0}" != "1" ] \
   && [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "embedding sidecar left warm (runner index ${RUNNER_INDEX}, pid $(cat "$PIDFILE"))"
  exit 0
fi
if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    # Poll instead of a flat 2 s: uvicorn exits in ~100 ms.
    for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
echo "embedding sidecar stopped (runner index ${RUNNER_INDEX})"
exit 0
