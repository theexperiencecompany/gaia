/**
 * Copy the onnxruntime-web WASM runtime into public/wake-word/ort/ so the wake-word pipeline (libs/wake-word) loads it from the same origin; synced from node_modules on dev/build since the binaries are large generated files, not committed.
 * Only the CPU WASM bundle is copied — libs/wake-word runs the "wasm" execution provider, so JSEP/WebGPU/WebNN, JSPI, and asyncify variants never load; the JSEP binary alone is 25MiB, over Cloudflare Workers' 25MiB per-asset limit, which would break the deploy.
 */
import { copyFileSync, mkdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Files the `onnxruntime-web/wasm` bundle fetches at runtime: the CPU WASM
// binary and its Emscripten glue. Keep this in sync with the bundle imported
// in libs/wake-word/src/web/runtime.ts.
const RUNTIME_FILES = [
  "ort-wasm-simd-threaded.wasm",
  "ort-wasm-simd-threaded.mjs",
];

const require = createRequire(import.meta.url);
// onnxruntime-web's exports map hides dist/, so resolve the package main
// entry (inside dist/) and use its directory.
const distDir = dirname(require.resolve("onnxruntime-web"));
const targetDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../public/wake-word/ort",
);

mkdirSync(targetDir, { recursive: true });

let copied = 0;
for (const file of RUNTIME_FILES) {
  const source = join(distDir, file);
  const target = join(targetDir, file);
  try {
    if (statSync(target).size === statSync(source).size) continue;
  } catch {
    // Target missing — copy below.
  }
  copyFileSync(source, target);
  copied++;
}

if (copied > 0) {
  console.log(
    `[wake-word] Synced ${copied} ONNX runtime file(s) to public/wake-word/ort`,
  );
}
