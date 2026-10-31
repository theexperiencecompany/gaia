#!/usr/bin/env bash
# Boots the built Cloudflare Worker locally (workerd — no account, no traffic)
# and asserts that real routes render and hydrate.
#
# A successful `cf:build` only proves the bundle assembles. Next 16.4 moved
# preview props into `.next/server/preview-props.json`; OpenNext 1.20.2's
# loader rejected it, and every dynamic route returned 500 in production while
# the build stayed green. This runs the thing: each route must answer 200 with
# its own <title> and no Next error page, then a browser loads the pages
# (apps/web/playwright.worker.config.ts) and fails on any uncaught error or
# unloaded chunk.
#
# `visual` instead screenshots the key marketing pages on the same booted worker
# (apps/web/playwright.visual.config.ts) and fails on any pixel that differs from
# the baseline; `visual update` captures that baseline, on the base branch's build.
#
#   bash scripts/ci/smoke-worker.sh
#   SMOKE_ROUTES=$'/login Login | GAIA\n/c New Chat | GAIA' bash scripts/ci/smoke-worker.sh
#   bash scripts/ci/smoke-worker.sh visual [update]
set -euo pipefail

MODE="${1:-smoke}"
case "$MODE" in
  smoke) ;;
  visual)
    VISUAL_UPDATE=""
    if [[ "${2:-}" == "update" ]]; then VISUAL_UPDATE=1; fi
    ;;
  *)
    echo "usage: smoke-worker.sh [visual [update]]" >&2
    exit 2
    ;;
esac

cd "$(dirname "$0")/../.."

PORT="${SMOKE_PORT:-8787}"
BASE_URL="http://127.0.0.1:${PORT}"
# "<route> <expected title>". `/` and `/pricing` are promoted to Workers Static
# Assets, so the worker never runs for them and they stayed 200 through the outage.
DEFAULT_ROUTES=(
  # A landing page the worker renders per request: the outage's first 500.
  "/login Login | GAIA"
  # A second landing page, so one page's own breakage is not the only signal.
  "/contact Contact the GAIA Team: Get Help or Send Feedback"
  # Outside [locale]: the root app tree, with its own layout.
  "/connect Connect an integration"
  # The whole (main) app shell: its layout is force-dynamic and middleware does no auth redirect.
  "/c/00000000-0000-0000-0000-000000000000 GAIA - Your Personal AI Assistant"
)
ROUTES=()
if [[ -n "${SMOKE_ROUTES:-}" ]]; then
  while IFS= read -r line; do ROUTES+=("$line"); done <<<"$SMOKE_ROUTES"
else
  ROUTES=("${DEFAULT_ROUTES[@]}")
fi
LOG="$(mktemp)"
BODY="$(mktemp)"
PID=""

# The worker is wrangler -> node -> workerd. It runs in a process group of its
# own (set -m) so all three stop together; wrangler is exec'd from its bin
# rather than through `pnpm exec`, whose binary re-spawns in a new group.
cleanup() {
  if [[ -n "$PID" ]]; then
    kill -TERM -- "-$PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 -- "-$PID" 2>/dev/null || break
      sleep 0.5
    done
    kill -KILL -- "-$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -f "$LOG" "$BODY"
}
trap cleanup EXIT

if [[ ! -f apps/web/.open-next/worker.js ]]; then
  echo "::error::no worker bundle at apps/web/.open-next — run cf:build first"
  exit 1
fi

set -m
( cd apps/web && exec node_modules/.bin/wrangler dev --port "$PORT" >"$LOG" 2>&1 ) &
PID=$!
set +m

for _ in $(seq 1 90); do
  grep -q "Ready on" "$LOG" && break
  sleep 1
done
if ! grep -q "Ready on" "$LOG"; then
  echo "::error::the worker did not boot"
  tail -30 "$LOG"
  exit 1
fi

if [[ "$MODE" == "visual" ]]; then
  cd apps/web
  export SMOKE_BASE_URL="$BASE_URL" VISUAL_UPDATE
  if [[ -n "$VISUAL_UPDATE" ]]; then
    pnpm exec playwright test --config playwright.visual.config.ts --update-snapshots
  else
    pnpm exec playwright test --config playwright.visual.config.ts
  fi
  exit 0
fi

fail=0
for entry in "${ROUTES[@]}"; do
  route="${entry%% *}"
  title="${entry#* }"
  code="$(curl -sS -o "$BODY" -w "%{http_code}" --max-time 30 "${BASE_URL}${route}" || echo 000)"
  if [[ "$code" != "200" ]]; then
    echo "::error::${route} returned ${code}"
  elif grep -q "__next_error__" "$BODY"; then
    echo "::error::${route} rendered the Next error page"
  elif ! grep -qF "<title>${title}</title>" "$BODY"; then
    echo "::error::${route} rendered without <title>${title}</title>"
  else
    echo "smoke: ${route} → 200, <title>${title}</title>"
    continue
  fi
  grep -iE "error|exception|loadManifest|Unexpected" "$LOG" | tail -6 || true
  fail=1
done

if ! ( cd apps/web && SMOKE_BASE_URL="$BASE_URL" pnpm exec playwright test --config playwright.worker.config.ts ); then
  echo "::error::the browser check failed on the booted worker"
  fail=1
fi

exit "$fail"
