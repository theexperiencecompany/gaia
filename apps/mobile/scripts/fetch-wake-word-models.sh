#!/usr/bin/env bash
# Stage the four ONNX wake-word models into apps/mobile/assets/wake-word/ so
# Metro can bundle them. Idempotent; run before `expo prebuild` / `pnpm ios`.

set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
MOBILE_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LIB_ROOT=$(cd "$MOBILE_ROOT/../../libs/wake-word" && pwd)

# Ensure the lib's models are present (downloads on first run).
bash "$LIB_ROOT/scripts/fetch-models.sh"

ASSETS_DIR="$MOBILE_ROOT/assets/wake-word"
mkdir -p "$ASSETS_DIR"
cp -f "$LIB_ROOT/models/melspectrogram.onnx" "$ASSETS_DIR/melspectrogram.onnx"
cp -f "$LIB_ROOT/models/embedding_model.onnx" "$ASSETS_DIR/embedding_model.onnx"
cp -f "$LIB_ROOT/models/silero_vad.onnx" "$ASSETS_DIR/silero_vad.onnx"
# Use the trained classifier if present, else fall back to the placeholder.
if [[ -f "$LIB_ROOT/models/hey_gaia.onnx" ]]; then
  cp -f "$LIB_ROOT/models/hey_gaia.onnx" "$ASSETS_DIR/hey_gaia.onnx"
else
  cp -f "$LIB_ROOT/models/hey_mycroft_v0.1.onnx" "$ASSETS_DIR/hey_gaia.onnx"
fi
echo "Wake-word assets ready in $ASSETS_DIR"
