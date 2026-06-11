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

echo "Done! Prepared Next.js server at: $PREPARED_DIR"
exit 0
