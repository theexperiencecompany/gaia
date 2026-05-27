#!/usr/bin/env bash
# Fetch the four openWakeWord-compatible ONNX models we ship with the lib.
# Idempotent: skips files that already exist with the correct size.

set -euo pipefail

cd "$(dirname "$0")/.."

MODELS_DIR="models"
BASE_URL="https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"

declare -A EXPECTED_SIZE=(
  [melspectrogram.onnx]=1087958
  [embedding_model.onnx]=1326578
  [silero_vad.onnx]=1807522
  [hey_mycroft_v0.1.onnx]=857691
)

mkdir -p "$MODELS_DIR"
for name in "${!EXPECTED_SIZE[@]}"; do
  expected="${EXPECTED_SIZE[$name]}"
  path="$MODELS_DIR/$name"
  if [[ -f "$path" ]]; then
    size=$(stat -f%z "$path" 2>/dev/null || stat -c%s "$path")
    if [[ "$size" == "$expected" ]]; then
      printf '  ok  %s (%d bytes)\n' "$name" "$size"
      continue
    fi
    printf '  refetch %s (size %d ≠ expected %d)\n' "$name" "$size" "$expected"
  fi
  printf '  fetch  %s ... ' "$name"
  curl -sSL -o "$path" "$BASE_URL/$name"
  size=$(stat -f%z "$path" 2>/dev/null || stat -c%s "$path")
  printf '%d bytes\n' "$size"
  if [[ "$size" != "$expected" ]]; then
    printf '  ERROR: %s downloaded with wrong size (%d ≠ %d)\n' "$name" "$size" "$expected" >&2
    exit 1
  fi
done

echo
echo "All models present in $MODELS_DIR/"
