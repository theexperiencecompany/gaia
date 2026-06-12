#!/usr/bin/env node
/**
 * Cross-platform Next.js standalone preparation for desktop packaging.
 *
 * Copies `apps/web/.next/standalone` into `apps/desktop/.next-server-prepared`
 * with dereferenced symlinks, overlays static/public assets, then prunes the
 * dead weight the desktop runtime never loads. This avoids shell/rsync
 * dependencies for Windows CI runners.
 *
 * Keep the prune behavior in sync with `prepare-next-server.sh` (mac/linux);
 * the two scripts must produce equivalent output.
 */

import { existsSync } from "node:fs";
import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(scriptDir, "../../web");
const standaloneDir = resolve(webDir, ".next/standalone");
const staticDir = resolve(webDir, ".next/static");
const publicDir = resolve(webDir, "public");
const preparedDir = resolve(scriptDir, "../.next-server-prepared");
const preparedWebDir = resolve(preparedDir, "apps/web");
const preparedNextDir = resolve(preparedWebDir, ".next");
const preparedStaticDir = resolve(preparedNextDir, "static");
const preparedPublicDir = resolve(preparedWebDir, "public");

const copyOpts = {
  recursive: true,
  dereference: true,
  force: true,
};

// (landing) routes the desktop/in-app UI still reaches in-window — never prune
// these. Everything else under the (landing) route group is marketing/SEO the
// desktop app never navigates to. Mirror of KEEP_LANDING_ROUTES in the .sh.
const KEEP_LANDING_ROUTES = new Set([
  "desktop-login",
  "login",
  "signup",
  "blog",
  "download",
  "privacy",
  "terms",
  "payment",
  "thanks",
  "profile",
  "contact",
  "support",
  "status",
  "request-feature",
]);

const PRERENDER_SUFFIXES = [
  "",
  ".segments",
  ".html",
  ".rsc",
  ".meta",
  ".prefetch.rsc",
];

async function copyIfExists(src, dest, label) {
  if (!existsSync(src)) {
    console.warn(`[warn] Skipping missing ${label}: ${src}`);
    return;
  }
  await mkdir(dest, { recursive: true });
  await cp(src, dest, copyOpts);
}

/** Recursively delete every file with the given extension under `dir`. */
async function deleteByExtension(dir, ext) {
  if (!existsSync(dir)) return;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      await deleteByExtension(full, ext);
    } else if (extname(entry.name) === ext) {
      await rm(full, { force: true });
    }
  }
}

/**
 * Strip onnxruntime-web wasm variants the wake-word engine never requests.
 * The default ESM entry loads the JSEP flavor
 * `ort-wasm-simd-threaded.jsep.{mjs,wasm}` even for the plain "wasm" execution
 * provider (JSEP is the unified CPU+WebGPU build). Keep that pair; drop the
 * plain, asyncify, and jspi flavors. Pruning jsep instead leaves the engine
 * with "no available backend found" and the wake word silently dead in
 * packaged builds — the canary below fails the build loudly if that happens.
 */
async function pruneOnnxRuntime(ortDir) {
  if (!existsSync(ortDir)) return;
  for (const name of await readdir(ortDir)) {
    const isUnusedFlavor =
      name.includes(".asyncify.") ||
      name.includes(".jspi.") ||
      name === "ort-wasm-simd-threaded.wasm" ||
      name === "ort-wasm-simd-threaded.mjs";
    if (isUnusedFlavor) await rm(resolve(ortDir, name), { force: true });
  }

  const jsepWasm = resolve(ortDir, "ort-wasm-simd-threaded.jsep.wasm");
  if (!existsSync(jsepWasm)) {
    throw new Error(
      `wake-word runtime '${jsepWasm}' missing after prune. The onnxruntime-web ` +
        "wasm flavor the engine loads may have changed — update the prune in " +
        "scripts/prepare-next-server.mjs (and .sh) to keep the right pair.",
    );
  }
}

/**
 * Remove prerendered marketing/SEO pages the desktop app never navigates to.
 * The desktop bundles the FULL (main) app, so we derive the prune set from the
 * web app's (landing) route group at build time (complete + self-maintaining)
 * and delete only those section names from the server output. (main)/(desktop)
 * route names never collide with (landing) names, so an in-app page is never
 * removed.
 */
async function pruneMarketingPages(serverAppDir) {
  const landingSrc = resolve(webDir, "src/app/[locale]/(landing)");
  if (!existsSync(landingSrc) || !existsSync(serverAppDir)) return;

  const sections = (await readdir(landingSrc, { withFileTypes: true }))
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    // Skip route groups "(group)" and dynamic segments "[slug]" — not prunable
    // by a static name — and the routes the app still reaches in-window.
    .filter(
      (name) =>
        !name.startsWith("(") &&
        !name.startsWith("[") &&
        !KEEP_LANDING_ROUTES.has(name),
    );

  for (const localeDir of await readdir(serverAppDir, { withFileTypes: true })) {
    if (!localeDir.isDirectory()) continue;
    const localeBase = resolve(serverAppDir, localeDir.name);
    for (const section of sections) {
      for (const suffix of PRERENDER_SUFFIXES) {
        await rm(resolve(localeBase, `${section}${suffix}`), {
          recursive: true,
          force: true,
        });
      }
    }
  }
}

async function prune() {
  console.log("Pruning sourcemaps, unused wasm variants, and SEO data...");
  // Browser sourcemaps (debugging only).
  await deleteByExtension(preparedNextDir, ".map");
  // onnxruntime-web wasm variants + wake-word canary.
  await pruneOnnxRuntime(resolve(preparedPublicDir, "wake-word/ort"));
  // Programmatic-SEO content data (feeds the pruned marketing pages;
  // loadFeatureTranslations returns {} gracefully when files are missing).
  await rm(resolve(preparedPublicDir, "data/i18n"), {
    recursive: true,
    force: true,
  });
  // Prerendered marketing pages.
  await pruneMarketingPages(resolve(preparedNextDir, "server/app"));
}

async function main() {
  console.log("Preparing Next.js standalone for electron-builder...");
  console.log(`From: ${standaloneDir}`);
  console.log(`To:   ${preparedDir}`);

  if (!existsSync(standaloneDir)) {
    throw new Error(
      `Standalone directory does not exist: ${standaloneDir}. Run 'nx build web' first.`,
    );
  }

  await rm(preparedDir, { recursive: true, force: true });
  await mkdir(preparedDir, { recursive: true });

  await cp(standaloneDir, preparedDir, copyOpts);
  await copyIfExists(staticDir, preparedStaticDir, ".next/static");
  await copyIfExists(publicDir, preparedPublicDir, "public");

  await prune();

  console.log(`Done! Prepared Next.js server at: ${preparedDir}`);
}

main().catch((error) => {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
