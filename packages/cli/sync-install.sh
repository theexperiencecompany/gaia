#!/bin/sh
# Sync install.sh to web app public directory

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SOURCE="$SCRIPT_DIR/install.sh"
DEST="$SCRIPT_DIR/../../apps/web/public/install.sh"

if [ ! -f "$SOURCE" ]; then
  echo "Error: Source install.sh not found at $SOURCE"
  exit 1
fi

cp "$SOURCE" "$DEST"
echo "✓ Synced install.sh to apps/web/public/"
