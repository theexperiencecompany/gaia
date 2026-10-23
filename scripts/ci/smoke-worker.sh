#!/usr/bin/env bash
# Boots the built Cloudflare Worker locally (workerd — no account, no traffic)
# and asserts that real routes render.
#
# A successful `cf:build` only proves the bundle assembles. Next 16.4 moved
# preview props into `.next/server/preview-props.json`; OpenNext 1.20.2's
# loader rejected it, and every dynamic route returned 500 in production while
# the build stayed green. This runs the thing.
#
#   bash scripts/ci/smoke-worker.sh
#   SMOKE_ROUTES="/ /login /c/00000000-0000-0000-0000-000000000000" ...
set -euo pipefail

cd "$(dirname "$0")/../.."

PORT="${SMOKE_PORT:-8787}"
ROUTES="${SMOKE_ROUTES:-/ /login /pricing}"
LOG="$(mktemp)"
PID=""

cleanup() {
  if [[ -n "$PID" ]]; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -f "$LOG"
}
trap cleanup EXIT

if [[ ! -f apps/web/.open-next/worker.js ]]; then
  echo "::error::no worker bundle at apps/web/.open-next — run cf:build first"
  exit 1
fi

( cd apps/web && pnpm exec wrangler dev --port "$PORT" >"$LOG" 2>&1 ) &
PID=$!

for _ in $(seq 1 90); do
  grep -q "Ready on" "$LOG" && break
  sleep 1
done
if ! grep -q "Ready on" "$LOG"; then
  echo "::error::the worker did not boot"
  tail -30 "$LOG"
  exit 1
fi

fail=0
for route in $ROUTES; do
  body="$(mktemp)"
  code="$(curl -sS -o "$body" -w "%{http_code}" --max-time 30 "http://127.0.0.1:${PORT}${route}" || echo 000)"
  if [[ "$code" != "200" ]]; then
    echo "::error::${route} returned ${code}"
    grep -iE "error|exception|loadManifest|Unexpected" "$LOG" | tail -6 || true
    fail=1
  else
    echo "smoke: ${route} → 200"
  fi
  rm -f "$body"
done

exit "$fail"
