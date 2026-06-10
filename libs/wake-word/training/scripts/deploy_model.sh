#!/usr/bin/env bash
# Deploy a trained hey_gaia.onnx into the apps and re-run the TS test harness
# to confirm everything still wires up.
#
#   bash scripts/deploy_model.sh
#
# Expected file: ../models/hey_gaia.onnx (produced by `src.train`).

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
TRAIN_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
LIB_ROOT=$(cd "$TRAIN_DIR/.." && pwd)
REPO=$(cd "$LIB_ROOT/../.." && pwd)

MODEL="$LIB_ROOT/models/hey_gaia.onnx"
if [[ ! -f "$MODEL" ]]; then
  echo "ERROR: $MODEL not found — run training first" >&2
  exit 1
fi

SIZE_KB=$(($(stat -f%z "$MODEL") / 1024))
echo "deploying $MODEL ($SIZE_KB KB)"

# Web — public assets
WEB_DIR="$REPO/apps/web/public/wake-word"
mkdir -p "$WEB_DIR"
cp -f "$MODEL" "$WEB_DIR/hey_gaia.onnx"
echo "  -> $WEB_DIR/hey_gaia.onnx"

# Mobile — bundled assets
MOBILE_DIR="$REPO/apps/mobile/assets/wake-word"
mkdir -p "$MOBILE_DIR"
cp -f "$MODEL" "$MOBILE_DIR/hey_gaia.onnx"
echo "  -> $MOBILE_DIR/hey_gaia.onnx"

echo
echo "deployed. To re-run the TS tests (which still use hey_mycroft for now):"
echo "  cd $LIB_ROOT && pnpm test"
echo "Production validation lives in libs/wake-word/training/src/validate.py."
