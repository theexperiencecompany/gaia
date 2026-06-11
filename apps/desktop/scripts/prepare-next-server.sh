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

rsync_safe -aL "$STANDALONE_DIR/" "$PREPARED_DIR/"

# Also copy static files (mkdir first — standalone rsync may not create these)
echo "Copying static files..."
mkdir -p "$PREPARED_DIR/apps/web/.next/static"
rsync_safe -aL "$WEB_DIR/.next/static/" "$PREPARED_DIR/apps/web/.next/static/"

mkdir -p "$PREPARED_DIR/apps/web/public"
rsync_safe -aL "$WEB_DIR/public/" "$PREPARED_DIR/apps/web/public/"

echo "Done! Prepared Next.js server at: $PREPARED_DIR"
exit 0
