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

rsync -aL "$STANDALONE_DIR/" "$PREPARED_DIR/" 2>&1
RSYNC_EXIT=$?
if [ $RSYNC_EXIT -ne 0 ] && [ $RSYNC_EXIT -ne 23 ]; then
  echo "ERROR: rsync failed with exit code $RSYNC_EXIT"
  exit 1
fi

# Also copy static files
echo "Copying static files..."
rsync -aL "$WEB_DIR/.next/static/" "$PREPARED_DIR/apps/web/.next/static/" 2>&1
RSYNC_EXIT=$?
if [ $RSYNC_EXIT -ne 0 ] && [ $RSYNC_EXIT -ne 23 ]; then
  echo "ERROR: Failed to copy static files with exit code $RSYNC_EXIT"
  exit 1
fi

rsync -aL "$WEB_DIR/public/" "$PREPARED_DIR/apps/web/public/" 2>&1
RSYNC_EXIT=$?
if [ $RSYNC_EXIT -ne 0 ] && [ $RSYNC_EXIT -ne 23 ]; then
  echo "ERROR: Failed to copy public files with exit code $RSYNC_EXIT"
  exit 1
fi

echo "Done! Prepared Next.js server at: $PREPARED_DIR"
exit 0
