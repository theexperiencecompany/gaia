#!/bin/bash
# Script to prepare Next.js standalone output for electron-builder
# Dereferences pnpm symlinks which break macOS code signing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/../../web"
STANDALONE_DIR="$WEB_DIR/.next/standalone"
PREPARED_DIR="$SCRIPT_DIR/../.next-server-prepared"

echo "Preparing Next.js standalone for electron-builder..."

# Check if standalone directory exists
if [ ! -d "$STANDALONE_DIR" ]; then
  echo "ERROR: Standalone directory does not exist: $STANDALONE_DIR"
  echo "Please run 'nx build web' first to generate the standalone output."
  exit 1
fi

# Remove old prepared directory
rm -rf "$PREPARED_DIR"

# Copy with dereferenced symlinks using rsync
# Exit code 23 = partial transfer (some symlinks can't be resolved, which is OK)
echo "Copying standalone output with dereferenced symlinks..."
echo "From: $STANDALONE_DIR/"
echo "To: $PREPARED_DIR/"

rsync_safe() {
  local exit_code
  rsync "$@" 2>&1 || exit_code=$?
  exit_code=${exit_code:-0}
  if [ "$exit_code" -ne 0 ] && [ "$exit_code" -ne 23 ]; then
    echo "ERROR: rsync failed with exit code $exit_code"
    return "$exit_code"
  fi
}

# Next.js standalone mirrors filesystem paths from the common ancestor of all
# traced files. Built from the primary repo, server.js sits at apps/web/server.js;
# built from a worktree (deps symlinked to the primary), output nests one level
# deeper (<worktree-name>/apps/web/server.js) with node_modules as a symlink to
# the primary repo and the real traced copy under <primary-name>/node_modules.
# The main process expects next-server/apps/web/server.js, so normalize here.
APP_ROOT=""
if [ -f "$STANDALONE_DIR/apps/web/server.js" ]; then
  APP_ROOT="$STANDALONE_DIR"
else
  for candidate in "$STANDALONE_DIR"/*/; do
    if [ -f "${candidate}apps/web/server.js" ]; then
      APP_ROOT="${candidate%/}"
      break
    fi
  done
fi

if [ -z "$APP_ROOT" ]; then
  echo "ERROR: Could not find apps/web/server.js in standalone output"
  exit 1
fi

NM_SRC="$APP_ROOT/node_modules"
if [ -L "$NM_SRC" ]; then
  for candidate in "$STANDALONE_DIR"/*/node_modules; do
    if [ -d "$candidate" ] && [ ! -L "$candidate" ]; then
      NM_SRC="$candidate"
      break
    fi
  done
fi

if [ ! -d "$NM_SRC" ] || [ -L "$NM_SRC" ]; then
  echo "ERROR: Could not find traced node_modules in standalone output"
  exit 1
fi

echo "App root: $APP_ROOT"
echo "node_modules source: $NM_SRC"

rsync_safe -aL --exclude='/node_modules' "$APP_ROOT/" "$PREPARED_DIR/"
rsync_safe -aL "$NM_SRC/" "$PREPARED_DIR/node_modules/"

# Also copy static files (mkdir first — standalone rsync may not create these)
echo "Copying static files..."
mkdir -p "$PREPARED_DIR/apps/web/.next/static"
rsync_safe -aL "$WEB_DIR/.next/static/" "$PREPARED_DIR/apps/web/.next/static/"

mkdir -p "$PREPARED_DIR/apps/web/public"
rsync_safe -aL "$WEB_DIR/public/" "$PREPARED_DIR/apps/web/public/"

# Strip dead weight the desktop runtime never loads:
# - browser sourcemaps (debugging only)
# - onnxruntime-web wasm variants the wake-word engine never requests. The
#   default ESM entry (what @gaia/wake-word imports) loads the JSEP flavor
#   `ort-wasm-simd-threaded.jsep.{mjs,wasm}` even for the plain "wasm"
#   execution provider — JSEP is the unified CPU+WebGPU build. Keep that pair;
#   drop the plain, asyncify, and jspi flavors the loader never fetches.
#   (Pruning jsep instead leaves the engine with "no available backend found"
#   and the wake word silently dead in packaged builds — dev keeps every
#   variant, so it only surfaces after packaging. The guard below fails the
#   build loudly if the jsep pair ever stops shipping under this name.)
# - programmatic-SEO content data (feeds the pruned marketing pages;
#   loadFeatureTranslations returns {} gracefully when files are missing)
echo "Pruning sourcemaps, unused wasm variants, and SEO data..."
find "$PREPARED_DIR/apps/web/.next" -name '*.map' -delete
ORT_DIR="$PREPARED_DIR/apps/web/public/wake-word/ort"
rm -f "$ORT_DIR/"*.asyncify.* "$ORT_DIR/"*.jspi.*
# Plain (non-jsep) pair — a different build flavor the loader does not request;
# delete by exact name so the jsep pair is preserved.
rm -f "$ORT_DIR/ort-wasm-simd-threaded.wasm" "$ORT_DIR/ort-wasm-simd-threaded.mjs"
rm -rf "$PREPARED_DIR/apps/web/public/data/i18n"

# Canary: the wake-word engine loads this exact file at runtime. If an
# onnxruntime-web upgrade renames the flavor (or the prune above deletes the
# wrong one), fail the build here — otherwise the wake word goes silently dead
# in packaged builds only, since dev keeps every variant.
JSEP_WASM="$ORT_DIR/ort-wasm-simd-threaded.jsep.wasm"
if [ ! -f "$JSEP_WASM" ]; then
  echo "ERROR: wake-word runtime '$JSEP_WASM' missing after prune."
  echo "The onnxruntime-web wasm flavor the engine loads may have changed —"
  echo "update the prune in scripts/prepare-next-server.sh to keep the right pair."
  exit 1
fi

# Strip prerendered marketing/SEO pages the desktop app never navigates to.
# The desktop bundles the FULL (main) app, so we must not touch its routes —
# instead we derive the prune set from the web app's (landing) route group at
# build time (so it stays complete as marketing adds pages) and delete only
# those section names from the server output. (main)/(desktop) route names
# never collide with (landing) names, so this can't remove an in-app page.
#
# KEEP_LANDING_ROUTES are the (landing) routes the desktop/in-app UI still
# reaches in-window — the desktop login page, auth, legal, transactional, and
# the marketing routes the authenticated app links to (blog, download).
LANDING_SRC="$WEB_DIR/src/app/[locale]/(landing)"
SERVER_APP_DIR="$PREPARED_DIR/apps/web/.next/server/app"
KEEP_LANDING_ROUTES=" desktop-login login signup blog download privacy terms payment thanks profile contact support status request-feature "

if [ -d "$LANDING_SRC" ] && [ -d "$SERVER_APP_DIR" ]; then
  echo "Pruning prerendered marketing pages..."
  for section_path in "$LANDING_SRC"/*/; do
    section="$(basename "$section_path")"
    # Skip nested route groups "(group)" and dynamic segments "[slug]" — not
    # prunable by a static name.
    case "$section" in
      \(*\) | \[*\]) continue ;;
    esac
    # Skip routes the app still reaches in-window.
    case "$KEEP_LANDING_ROUTES" in
      *" $section "*) continue ;;
    esac
    for locale_dir in "$SERVER_APP_DIR"/*/; do
      rm -rf \
        "${locale_dir}${section}" \
        "${locale_dir}${section}.segments" \
        "${locale_dir}${section}.html" \
        "${locale_dir}${section}.rsc" \
        "${locale_dir}${section}.meta" \
        "${locale_dir}${section}.prefetch.rsc"
    done
  done
fi

echo "Done! Prepared Next.js server at: $PREPARED_DIR"
exit 0
