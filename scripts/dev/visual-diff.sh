#!/usr/bin/env bash
# Screenshot every web surface on a base ref and on the working tree, then diff them.
#
#   scripts/dev/visual-diff.sh [base-ref] [--app]
#
# Base renders from a throwaway worktree, head from this checkout; both are
# driven by HEAD's spec so they walk the same surface list (e2e/visual/surfaces.ts).
# --app adds the authenticated (main) routes and needs `mise dev --sim` running.
# VISUAL_GREP=<regex> captures only matching surfaces, e.g. VISUAL_GREP='\bapp /' (titles are "<group> <path>").
# Output: $VISUAL_OUT (default .context/visual-diff) — summary.md, ledger.md
# (every class/prop swap the diff makes), composites/, report/ (Playwright HTML
# report with side-by-side and slider views).
set -euo pipefail

BASE_REF="origin/master"
APP=0
for arg in "$@"; do
  case "$arg" in
    --app) APP=1 ;;
    -*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *) BASE_REF="$arg" ;;
  esac
done

ROOT=$(git rev-parse --show-toplevel)
OUT=$(mkdir -p "${VISUAL_OUT:-$ROOT/.context/visual-diff}" && builtin cd "${VISUAL_OUT:-$ROOT/.context/visual-diff}" && pwd)
PORT=${VISUAL_PORT:-3917}
BASE_DIR=$(mktemp -d)/base
SERVER_PID=""

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  git -C "$ROOT" worktree remove --force "$BASE_DIR" 2>/dev/null || true
}
trap cleanup EXIT

rm -rf "$OUT"/{baseline,results,report,composites,logs} "$OUT"/results.json "$OUT"/summary.* "$OUT"/ledger.md
mkdir -p "$OUT/logs"

BASE_SHA=$(git -C "$ROOT" rev-parse --short "$BASE_REF")

echo "==> base worktree at $BASE_REF ($BASE_SHA)"
git -C "$ROOT" worktree add --detach --quiet "$BASE_DIR" "$BASE_REF"
for env_file in "$ROOT"/apps/web/.env "$ROOT"/apps/web/.env.local; do
  [ -f "$env_file" ] && cp -f "$env_file" "$BASE_DIR/apps/web/"
done
(builtin cd "$BASE_DIR" && pnpm install --frozen-lockfile --prefer-offline >"$OUT/logs/base-install.log" 2>&1)

# Start a Next dev server for one checkout and block until it answers.
serve() {
  local web_dir="$1" log="$2"
  (builtin cd "$web_dir" && exec pnpm exec next dev --turbopack --port "$PORT") >"$log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 120); do
    curl -sf -o /dev/null "http://localhost:$PORT/" && return 0
    kill -0 "$SERVER_PID" 2>/dev/null || { echo "dev server died, see $log" >&2; exit 1; }
    sleep 2
  done
  echo "dev server did not answer on :$PORT within 240s, see $log" >&2
  exit 1
}

stop() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}

capture() {
  (builtin cd "$ROOT/apps/web" && VISUAL_OUT="$OUT" VISUAL_BASE_URL="http://localhost:$PORT" VISUAL_APP="$APP" \
    pnpm exec playwright test --config playwright.visual.config.ts "$@")
}

# A dev server can die under a long run; restart it once and re-run only what failed,
# so a crash never reads as "no baseline" or a render failure.
capture_resilient() {
  local web_dir="$1" log="$2"
  shift 2
  capture "$@" || true
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "    dev server died mid-run (see $log); restarting and re-running the failed surfaces"
    serve "$web_dir" "$log.restart"
    capture --last-failed "$@" || true
  fi
  stop
}

echo "==> recording base"
serve "$BASE_DIR/apps/web" "$OUT/logs/base-server.log"
# A surface base cannot render fails here and simply has no baseline.
capture_resilient "$BASE_DIR/apps/web" "$OUT/logs/base-server.log" \
  --update-snapshots=all --reporter=line >"$OUT/logs/base-capture.log" 2>&1

echo "==> comparing head"
# Labelled when head is captured, not at start: the tree may move during the base run.
HEAD_LABEL="$(git -C "$ROOT" branch --show-current) @ $(git -C "$ROOT" rev-parse --short HEAD)"
git -C "$ROOT" diff --quiet || HEAD_LABEL="$HEAD_LABEL + uncommitted"
serve "$ROOT/apps/web" "$OUT/logs/head-server.log"
# Differences fail the run by design; compose reads them from results.json.
capture_resilient "$ROOT/apps/web" "$OUT/logs/head-server.log"

(builtin cd "$ROOT/apps/web" && node e2e/visual/compose.ts "$OUT" "$BASE_REF @ $BASE_SHA" "$HEAD_LABEL" \
  && node e2e/visual/ledger.ts "$BASE_REF" "$OUT")
echo "==> $OUT/summary.md + ledger.md · open $OUT/report/index.html for side-by-side and slider views"
