#!/usr/bin/env bash
# One command per side of the HeroUI review. Run on the capture machine (the M4).
#
#   run.sh before <git-ref>   seed the API, build + capture v2 (twice), write review.html
#   run.sh after  <git-ref>   build + capture v3 (twice), change log, full review.html
#   run.sh report             recompare and re-render from existing captures
#   run.sh publish            serve $REVIEW_OUT on the Tailscale address
#
# Env: REVIEW_HOME (default ~/v3review), REVIEW_OUT (default $REVIEW_HOME/out),
#      RESEED=1 to rebuild the dataset (invalidates an existing before capture),
#      REDISCOVER=1 to regenerate states.json, WORKERS (default 4).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW_HOME="${REVIEW_HOME:-$HOME/v3review}"
OUT="${REVIEW_OUT:-$REVIEW_HOME/out}"
WORKERS="${WORKERS:-4}"
PUBLISH_ADDR="${PUBLISH_ADDR:-100.65.57.85}"
PUBLISH_PORT="${PUBLISH_PORT:-8765}"
STACK="$HERE/stack.sh"
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/opt/homebrew/bin:$PATH"
mkdir -p "$OUT"

die() { echo "run.sh: $*" >&2; exit 1; }
api_up() { curl -sf -o /dev/null --max-time 3 http://127.0.0.1:8100/health; }

capture_twice() {
  local label="$1"
  for run in 1 2; do node "$HERE/capture.mjs" --label "$label" --run "$run" --out "$OUT" --workers "$WORKERS"; done
}

report() {
  node "$HERE/compare.mjs" --out "$OUT"
  node "$HERE/html.mjs" --out "$OUT"
}

publish() {
  local pidf="$OUT/.http.pid"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then echo "already serving http://$PUBLISH_ADDR:$PUBLISH_PORT/review.html"; return; fi
  (cd "$OUT" && exec python3 -m http.server "$PUBLISH_PORT" --bind "$PUBLISH_ADDR") > "$OUT/.http.log" 2>&1 &
  echo $! > "$pidf"
  sleep 1
  kill -0 "$(cat "$pidf")" 2>/dev/null || die "http.server failed: $(cat "$OUT/.http.log")"
  echo "serving http://$PUBLISH_ADDR:$PUBLISH_PORT/review.html"
}

cmd_before() {
  local ref="$1"
  bash "$STACK" tree before "$ref"
  api_up || bash "$STACK" api
  if [ "${RESEED:-}" = 1 ] || [ ! -f "$OUT/seed-state.json" ]; then
    rm -rf "$OUT/shots/before" "$OUT/shots/after"
    node "$HERE/seed.mjs" --out "$OUT" --api-tree "$REVIEW_HOME/before"
  fi
  bash "$STACK" build before
  git -C "$REVIEW_HOME/before" rev-parse HEAD > "$OUT/before.sha"
  node "$HERE/inventory.mjs" --tree "$REVIEW_HOME/before" --out "$OUT"
  bash "$STACK" stop before; bash "$STACK" serve before
  if [ "${REDISCOVER:-}" = 1 ] || ! node -e '
    const s = require(process.argv[1]); const inv = require(process.argv[2]);
    process.exit(inv.targets.every((t) => Array.isArray(s[t.key])) ? 0 : 1);' "$HERE/states.json" "$OUT/inventory.json" 2>/dev/null; then
    [ -f "$HERE/states.json" ] || echo '{}' > "$HERE/states.json"
    node "$HERE/discover.mjs" --out "$OUT"
  fi
  rm -rf "$OUT/shots/before"
  capture_twice before
  report
  publish
}

cmd_after() {
  local ref="$1"
  [ -f "$OUT/before.sha" ] || die "capture the before side first: run.sh before <ref>"
  bash "$STACK" tree after "$ref"
  api_up || bash "$STACK" api
  bash "$STACK" build after
  git -C "$REVIEW_HOME/after" rev-parse HEAD > "$OUT/after.sha"
  bash "$STACK" stop after; bash "$STACK" serve after
  rm -rf "$OUT/shots/after"
  capture_twice after
  node "$HERE/changelog.mjs" --repo "$REVIEW_HOME/after" --before "$(cat "$OUT/before.sha")" --after "$(cat "$OUT/after.sha")" --out "$OUT"
  report
  publish
}

sub="${1:-}"; shift || true
case "$sub" in
  before|after) [ $# -eq 1 ] || die "usage: run.sh $sub <git-ref>"; "cmd_$sub" "$1" ;;
  report) report ;;
  publish) publish ;;
  *) die "usage: run.sh before <ref> | after <ref> | report | publish" ;;
esac
