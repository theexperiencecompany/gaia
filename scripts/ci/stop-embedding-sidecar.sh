#!/usr/bin/env bash
# stop-embedding-sidecar.sh — stop the sidecar started by start-embedding-sidecar.sh.
# Never fails the caller: it runs in teardown positions.
set -uo pipefail
RUNNER_INDEX="${RUNNER_INDEX:-0}"
PIDFILE="/tmp/gaia-embedding-sidecar-${RUNNER_INDEX}.pid"
if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
echo "embedding sidecar stopped (runner index ${RUNNER_INDEX})"
exit 0
