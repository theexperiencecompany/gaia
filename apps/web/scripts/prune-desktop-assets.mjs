#!/usr/bin/env node
/**
 * Remove desktop-only assets from the Cloudflare build output.
 *
 * Why: `public/` is shared by every build target, but some assets are only
 * ever served to the Electron desktop shell — which loads them from its OWN
 * embedded Next.js standalone server on localhost (see apps/desktop
 * server.ts / windows/load-url.ts), never from the Cloudflare URL. Shipping
 * them to the edge is dead weight: no Cloudflare-served browser fetches them.
 *
 * The wake-word ONNX runtime is the whole of this set:
 *  - the `/wake-listener` route lives in the (desktop) route group, loaded
 *    exclusively by Electron;
 *  - the dev-only `/dev/wake-word` page is stripped from production builds.
 * That makes `public/wake-word/` (~17 MiB: a 12 MiB WASM binary + ONNX
 * models) unreachable on the web.
 *
 * OpenNext copies `public/` into TWO places, and the wake-word tree must be
 * removed from both:
 *  - `.open-next/assets/` — the Workers Static Assets layer (25 MiB
 *    per-file limit; the 25 MiB JSEP wasm tripped this).
 *  - `.open-next/server-functions/<fn>/apps/web/public/` — bundled INTO the
 *    Worker script (10 MiB total-script limit; the 12.7 MiB CPU wasm tripped
 *    this). This is the copy the Node server would read at runtime, which on
 *    Cloudflare never happens for these files.
 *
 * The standalone build Electron bundles is produced separately and keeps
 * `public/wake-word/` intact.
 *
 * Run AFTER `opennextjs-cloudflare build`, alongside promote-static.
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
