#!/usr/bin/env node
/**
 * Remove desktop-only wake-word ONNX assets (~17MiB: WASM + ONNX models, used only by Electron's own embedded server via apps/desktop server.ts / windows/load-url.ts) from the Cloudflare build output — dead weight since no Cloudflare-served browser needs them.
 * OpenNext copies public/ into two places that must both be pruned: .open-next/assets/ (25MiB per-file limit, tripped by the JSEP wasm) and .open-next/server-functions/<fn>/apps/web/public/ (10MiB total-script limit, tripped by the 12.7MiB CPU wasm).
 * Run after `opennextjs-cloudflare build`, alongside promote-static; the Electron standalone build keeps public/wake-word/ intact.
 */
import { existsSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const OPEN_NEXT_DIR = join(root, ".open-next");

// Asset directory names that exist only for the Electron desktop shell.
const DESKTOP_ONLY_DIRS = new Set(["wake-word"]);

if (!existsSync(OPEN_NEXT_DIR)) {
  console.error(
    `[prune-desktop-assets] .open-next missing: ${OPEN_NEXT_DIR} — run the build first.`,
  );
  process.exit(1);
}

/**
 * Recursively collect every desktop-only directory under `dir`. Does not
 * descend into a match (nothing useful lives below it).
 */
function collect(dir, found) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch (error) {
    // A directory may vanish between discovery and read; that's expected.
    // Any other failure (permissions, I/O) must fail the build loudly rather
    // than silently skip pruning and ship a too-large Worker.
    if (error?.code === "ENOENT") return found;
    throw error;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const full = join(dir, entry.name);
    if (DESKTOP_ONLY_DIRS.has(entry.name)) {
      found.push(full);
    } else {
      collect(full, found);
    }
  }
  return found;
}

const targets = collect(OPEN_NEXT_DIR, []);
for (const target of targets) {
  rmSync(target, { recursive: true, force: true });
}

console.log(
  targets.length
    ? `[prune-desktop-assets] removed ${targets.length} desktop-only tree(s) from the Cloudflare build:\n${targets
        .map((t) => `  - ${relative(root, t)}`)
        .join("\n")}`
    : "[prune-desktop-assets] no desktop-only assets present — nothing to prune.",
);
