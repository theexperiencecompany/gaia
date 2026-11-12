#!/usr/bin/env bash
# Review a candidate build against the v2 reference, one area group at a time.
#
#   candidate.sh <name> <web-dir> <port> <area[,area...]>
#
#   <name>     short id; results land in $REVIEW_OUT/candidates/<name>/, served under /candidates/<name>/
#   <web-dir>  an apps/web directory holding a finished `next build` (.next/standalone, .next/static, public)
#              built with NEXT_PUBLIC_API_BASE_URL=http://localhost:8100/api/v1/ (stack.sh build does this)
#   <port>     a free localhost port to serve it on (not 3210/3211/8100)
#   <area>     inventory areas: marketing auth chat todos calendar workflows app settings onboarding "desktop popup"
#
# Reuses the main review's seed, inventory, states and v2 shots (hardlinked, read-only), captures the
# candidate twice for those areas, and writes report/areas/<name>.json plus diff PNGs in the candidate dir.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW_HOME="${REVIEW_HOME:-$HOME/v3review}"
MAIN="${REVIEW_OUT:-$REVIEW_HOME/out}"
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/opt/homebrew/bin:$PATH"
die() { echo "candidate.sh: $*" >&2; exit 1; }

[ $# -eq 4 ] || die "usage: candidate.sh <name> <web-dir> <port> <area[,area...]>"
NAME="$1"; WEB="$(cd "$2" && pwd)"; PORT="$3"; AREAS="$4"
OUT="$MAIN/candidates/$NAME"
APP="$WEB/.next/standalone/apps/web"
[ -f "$APP/server.js" ] || die "no standalone build at $APP (run next build with output: standalone first)"
[ -f "$MAIN/shots/before/run1/manifest.json" ] || die "no v2 reference in $MAIN"
curl -sf -o /dev/null --max-time 3 http://127.0.0.1:8100/health || die "the seeded API is not up on :8100 (stack.sh api)"
if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then die "port $PORT is taken"; fi

rm -rf "$OUT"; mkdir -p "$OUT/shots"
cp "$MAIN/seed-state.json" "$MAIN/inventory.json" "$MAIN/before.sha" "$OUT/"
cp -Rl "$MAIN/shots/before" "$OUT/shots/before"
ln -s "$MAIN/netcache" "$OUT/netcache"
git -C "$WEB" rev-parse HEAD > "$OUT/after.sha"

rm -rf "$APP/.next/static" "$APP/public"
cp -R "$WEB/.next/static" "$APP/.next/static"
cp -R "$WEB/public" "$APP/public"
# HOSTNAME=localhost: on any other host Next proxies the i18n rewrite back through the middleware and loops.
(cd "$APP" && NODE_ENV=production PORT="$PORT" HOSTNAME=localhost exec node server.js) > "$OUT/web.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 120); do curl -sf -o /dev/null --max-time 3 "http://localhost:$PORT/about" && break; kill -0 $SERVER || die "server exited: $(tail -5 "$OUT/web.log")"; sleep 1; done

for run in 1 2; do
  node "$HERE/capture.mjs" --label after --run "$run" --base "http://localhost:$PORT" --out "$OUT" --areas "$AREAS" --workers "${WORKERS:-6}"
done
node "$HERE/compare.mjs" --out "$OUT" --areas "$AREAS" --name "$NAME"
echo "results: $OUT/report/areas/$NAME.json (paths in it are relative to $OUT)"
