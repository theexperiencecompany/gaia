#!/usr/bin/env node
/**
 * Remove desktop-only assets from the Cloudflare Workers Static Assets dir.
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
 * models) unreachable on the web. Pruning it also keeps the deploy under
 * Cloudflare's 25 MiB per-asset limit with margin to spare.
 *
 * This only touches `.open-next/assets` (the Cloudflare output). The
 * standalone build Electron bundles keeps `public/wake-word/` intact.
 *
 * Run AFTER `opennextjs-cloudflare build`, alongside promote-static.
 */
import { existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const ASSETS_DIR = join(root, ".open-next/assets");

// Asset subtrees served only by the Electron desktop shell's local server.
const DESKTOP_ONLY_ASSETS = ["wake-word"];

if (!existsSync(ASSETS_DIR)) {
  console.error(
    `[prune-desktop-assets] assets dir missing: ${ASSETS_DIR} — run the build first.`,
  );
  process.exit(1);
}

const pruned = [];
for (const entry of DESKTOP_ONLY_ASSETS) {
  const target = join(ASSETS_DIR, entry);
  if (existsSync(target)) {
    rmSync(target, { recursive: true, force: true });
    pruned.push(entry);
  }
}

console.log(
  pruned.length
    ? `[prune-desktop-assets] removed desktop-only asset(s) from worker bundle: ${pruned.join(", ")}`
    : "[prune-desktop-assets] no desktop-only assets present — nothing to prune.",
);
