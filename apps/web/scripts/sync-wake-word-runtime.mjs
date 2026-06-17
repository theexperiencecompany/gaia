/**
 * Copies the onnxruntime-web WASM runtime into public/wake-word/ort/
 * so the wake-word pipeline (libs/wake-word) can load it from the same
 * origin. The runtime is ~25 MB of generated binaries, so it is synced
 * from node_modules on dev/build instead of being committed.
 */
import { copyFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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
for (const file of readdirSync(distDir)) {
  if (!file.startsWith("ort-wasm-simd-threaded")) continue;
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
  console.log(`[wake-word] Synced ${copied} ONNX runtime file(s) to public/wake-word/ort`);
}
