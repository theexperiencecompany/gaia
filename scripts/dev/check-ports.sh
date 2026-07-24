#!/usr/bin/env bash
# Fail loud before a dev stack boots if any of its ports is already taken.
#
# Without this, `nx run-many -t dev` half-boots: uvicorn prints
# "[Errno 48] Address already in use", exits, and nx keeps the *other* projects
# running. The result looks healthy (the port answers — from the stale process)
# and every downstream check silently targets the wrong server. A leftover dev
# server from another worktree is the common cause.
#
# Usage: check-ports.sh NAME=PORT [NAME=PORT ...]

set -euo pipefail

taken=0

for pair in "$@"; do
  name="${pair%%=*}"
  port="${pair#*=}"
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  [ -n "$pid" ] || continue

  taken=1
  command="$(ps -o command= -p "$pid" 2>/dev/null | head -1 || echo 'unknown process')"
  echo "ERROR: $name port $port is already in use by PID $pid" >&2
  echo "         $command" >&2
done

if [ "$taken" -ne 0 ]; then
  cat >&2 <<'EOF'

Stop the process above, or give this worktree its own ports:

    mise run wt:env    # writes .env.worktree; mise loads it for every task

EOF
  exit 1
fi
