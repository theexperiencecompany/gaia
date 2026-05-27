#!/usr/bin/env bash
# Copy onnxruntime-web's WASM artifacts into public/wake-word/ort/ so the
# browser can fetch them at runtime. Run once per checkout (and on ORT bumps).
set -euo pipefail
WEB_DIR=$(cd "$(dirname "$0")/.." && pwd)
SRC=$(node -e "console.log(require.resolve('onnxruntime-web/package.json'))" | xargs dirname)/dist
OUT="$WEB_DIR/public/wake-word/ort"
mkdir -p "$OUT"
for f in ort-wasm-simd-threaded.wasm ort-wasm-simd-threaded.mjs ort-wasm-simd-threaded.jsep.wasm ort-wasm-simd-threaded.jsep.mjs; do
  cp -f "$SRC/$f" "$OUT/$f"
done
echo "Copied ORT WASM to $OUT"
