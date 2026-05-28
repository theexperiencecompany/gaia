#!/usr/bin/env bash
# cf-build.sh — One-shot Cloudflare Worker build + size analysis for apps/web.
#
# What it does:
#   1. Runs `next build` (skipping Sentry source-map upload by default for speed)
#   2. Patches .next/server/functions-config-manifest.json to remove the
#      Node-runtime /_middleware entry (proxy.ts in Next 16 always declares
#      Node, which OpenNext for Cloudflare hard-rejects). This is a build-output
#      patch only; source code is untouched.
#   3. Runs `opennextjs-cloudflare build --skipNextBuild` to produce the worker
#   4. Reports handler.mjs size + per-feature breakdown via existing
#      apps/web/scripts/analyze-handler-detail.py
#
# Flags:
#   --no-sentry   (default) skip the slow Sentry source-map upload
#   --sentry      run the full build with Sentry upload (matches Vercel)
#   --no-minify   pass --noMinify to OpenNext (much larger but readable handler.mjs)
#   --deploy      after build, run `wrangler deploy` (needs `wrangler login` or
#                 CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID env)
#   --preview     deploy a preview version (URL printed at end, no production)
#
# Usage:
#   ./scripts/cf-build.sh                    # build + analyze, no deploy
#   ./scripts/cf-build.sh --no-minify        # readable handler for grep/inspection
#   ./scripts/cf-build.sh --preview          # build + push to a preview URL
#   ./scripts/cf-build.sh --sentry --deploy  # production build + deploy

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT/apps/web"
SENTRY=0
MINIFY=1
DEPLOY=0
PREVIEW=0

for arg in "$@"; do
  case "$arg" in
    --sentry)    SENTRY=1 ;;
    --no-sentry) SENTRY=0 ;;
    --no-minify) MINIFY=0 ;;
    --deploy)    DEPLOY=1 ;;
    --preview)   PREVIEW=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

cd "$WEB_DIR"

echo ""
echo "▶ 1/4  Cleaning .next and .open-next"
rm -rf .next .open-next

echo ""
echo "▶ 2/4  next build${SENTRY:+ (with Sentry source-map upload)}"
if [[ $SENTRY -eq 0 ]]; then
  SENTRY_AUTH_TOKEN= pnpm exec next build
else
  pnpm exec next build
fi

echo ""
echo "▶ 3/4  Patching functions-config-manifest.json (drop Node /_middleware)"
node <<'JS'
const fs = require('fs');
const p = '.next/server/functions-config-manifest.json';
const j = JSON.parse(fs.readFileSync(p, 'utf8'));
if (j.functions && j.functions['/_middleware']) {
  delete j.functions['/_middleware'];
  fs.writeFileSync(p, JSON.stringify(j, null, 2));
  console.log('   ✓ removed /_middleware');
} else {
  console.log('   = nothing to patch');
}
JS

echo ""
echo "▶ 4/5  opennextjs-cloudflare build --skipNextBuild${MINIFY:+ (minified)}"
OPENNEXT_FLAGS="--skipNextBuild"
if [[ $MINIFY -eq 0 ]]; then OPENNEXT_FLAGS="$OPENNEXT_FLAGS --noMinify"; fi
pnpm exec opennextjs-cloudflare build $OPENNEXT_FLAGS

echo ""
echo "▶ 5/5  Stripping oversized assets (CF per-asset limit is 25 MiB)"
# Cloudflare Workers rejects single assets > 25 MiB. Find any files in
# .open-next/assets above the threshold and remove them from the upload set —
# the source file in public/ is left untouched, but it won't ship to CF.
# Long-term they should move to R2 or Cloudflare Stream.
find .open-next/assets -type f -size +25M -print | while read -r f; do
  echo "   ✗ removing $(du -h "$f" | cut -f1)  $f"
  rm -f "$f"
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo " BUILD COMPLETE"
echo "════════════════════════════════════════════════════════════════"

HANDLER=".open-next/server-functions/default/apps/web/handler.mjs"
WORKER=".open-next/worker.js"
SIZE_KB=$(du -k "$HANDLER" 2>/dev/null | cut -f1)
SIZE_MB=$(echo "scale=2; $SIZE_KB / 1024" | bc)
WORKER_KB=$(du -k "$WORKER" 2>/dev/null | cut -f1)
WORKER_MB=$(echo "scale=2; $WORKER_KB / 1024" | bc)

echo " handler.mjs : ${SIZE_MB} MB"
echo " worker.js   : ${WORKER_MB} MB"
echo ""
echo " Cloudflare Worker limits:"
echo "   Free tier   :  3 MB  $([[ $SIZE_KB -gt 3072 ]] && echo "❌ over" || echo "✅")"
echo "   Paid plan   : 10 MB  $([[ $SIZE_KB -gt 10240 ]] && echo "❌ over" || echo "✅")"
echo ""

if [[ -f scripts/analyze-handler-detail.py ]]; then
  echo "Running analyze-handler-detail.py..."
  python3 scripts/analyze-handler-detail.py | head -60
fi

if [[ $PREVIEW -eq 1 ]]; then
  echo ""
  echo "▶ Deploying preview…"
  pnpm exec opennextjs-cloudflare preview
elif [[ $DEPLOY -eq 1 ]]; then
  echo ""
  echo "▶ Deploying to production…"
  pnpm exec opennextjs-cloudflare deploy
fi
