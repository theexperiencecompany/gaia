#!/usr/bin/env node
/**
 * Cross-platform Next.js standalone preparation for electron-builder.
 *
 * THE single prepare script for every platform (mac/win/linux) — there is no
 * shell variant, by design: two scripts doing the same job in two languages
 * drift apart silently (Windows once shipped without the prune + wake-word
 * canary). One code path = no platform divergence.
 *
 * Steps:
 *   1. Locate the standalone app root (handles both the primary checkout
 *      layout and the deeper-nested layout produced by git worktree builds).
 *   2. Copy it — with the real (dereferenced) traced node_modules — into
 *      apps/desktop/.next-server-prepared, overlaying static + public assets.
 *   3. Prune the dead weight the desktop runtime never loads, and assert the
 *      wake-word runtime survived (the canary).
 */

import { existsSync, lstatSync, readdirSync } from "node:fs";
import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, extname, resolve, sep } from "node:path";
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

const copyOpts = { recursive: true, dereference: true, force: true };

// (landing) routes the desktop/in-app UI still reaches in-window — never
// prune these. Everything else under the (landing) route group is marketing/
// SEO the desktop app never navigates to.
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

const SERVER_ENTRY = "apps/web/server.js";

/**
 * Find the directory that contains `apps/web/server.js`. Next.js standalone
 * mirrors filesystem paths from the common ancestor of all traced files:
 * built from the primary repo this is `standalone/`; built from a worktree
 * (deps symlinked to primary) it nests one level deeper.
 */
function findAppRoot() {
  if (existsSync(resolve(standaloneDir, SERVER_ENTRY))) return standaloneDir;
  for (const entry of readdirSync(standaloneDir, { withFileTypes: true })) {
    if (
      entry.isDirectory() &&
      existsSync(resolve(standaloneDir, entry.name, SERVER_ENTRY))
    ) {
      return resolve(standaloneDir, entry.name);
    }
  }
  throw new Error(`Could not find ${SERVER_ENTRY} in ${standaloneDir}`);
}

/**
 * The real traced node_modules. In a worktree build `appRoot/node_modules` is
 * a symlink to the primary repo; the real traced copy lives under a sibling
 * standalone subdir. Prefer a real (non-symlink) directory.
 */
function findNodeModules(appRoot) {
  const direct = resolve(appRoot, "node_modules");
  if (existsSync(direct) && !lstatSync(direct).isSymbolicLink()) return direct;
  for (const entry of readdirSync(standaloneDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const candidate = resolve(standaloneDir, entry.name, "node_modules");
    if (existsSync(candidate) && !lstatSync(candidate).isSymbolicLink()) {
      return candidate;
    }
  }
  return direct;
}

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
    if (entry.isDirectory()) await deleteByExtension(full, ext);
    else if (extname(entry.name) === ext) await rm(full, { force: true });
  }
}

// The onnxruntime-web artifacts the wake-word engine actually fetches at
// runtime. `libs/wake-word/src/web/runtime.ts` imports `onnxruntime-web/wasm`
// and runs the plain "wasm" execution provider, which loads the CPU wasm binary
// plus its Emscripten glue. The JSEP/WebGPU, asyncify, and JSPI flavors are
// never loaded — and the JSEP binary alone (25 MiB) exceeds Cloudflare Workers'
// per-asset cap, so it is deliberately kept out of the synced runtime. Keep this
// in lockstep with RUNTIME_FILES in apps/web/scripts/sync-wake-word-runtime.mjs.
const ORT_RUNTIME_FILES = new Set([
  "ort-wasm-simd-threaded.wasm",
  "ort-wasm-simd-threaded.mjs",
]);
const ORT_CANARY_FILE = "ort-wasm-simd-threaded.wasm";

/**
 * Strip onnxruntime-web wasm variants the wake-word engine never requests,
 * keeping only the CPU wasm pair the "wasm" provider loads. The canary fails
 * the build loudly if that load-bearing binary ever goes missing — a packaged
 * build without it leaves the engine with "no available backend found" and the
 * wake word silently dead.
 */
async function pruneOnnxRuntime(ortDir) {
  if (!existsSync(ortDir)) return;
  for (const name of await readdir(ortDir)) {
    if (!ORT_RUNTIME_FILES.has(name)) await rm(resolve(ortDir, name), { force: true });
  }
  const canaryWasm = resolve(ortDir, ORT_CANARY_FILE);
  if (!existsSync(canaryWasm)) {
    throw new Error(
      `wake-word runtime '${canaryWasm}' missing after prune. The onnxruntime-web ` +
        "wasm flavor the engine loads may have changed — update pruneOnnxRuntime().",
    );
  }
}

/**
 * Remove prerendered marketing/SEO pages the desktop app never navigates to.
 * The desktop bundles the FULL (main) app, so the prune set is derived from
 * the web app's (landing) route group at build time (complete + self-
 * maintaining); only those section names are deleted from the server output.
 * (main)/(desktop) route names never collide with (landing) names, so an
 * in-app page is never removed.
 */
async function pruneMarketingPages(serverAppDir) {
  const landingSrc = resolve(webDir, "src/app/[locale]/(landing)");
  if (!existsSync(landingSrc) || !existsSync(serverAppDir)) return;

  const sections = (await readdir(landingSrc, { withFileTypes: true }))
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    // Skip route groups "(group)", dynamic segments "[slug]", and the routes
    // the app still reaches in-window.
    .filter(
      (n) =>
        !n.startsWith("(") && !n.startsWith("[") && !KEEP_LANDING_ROUTES.has(n),
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
  await deleteByExtension(preparedNextDir, ".map");
  await pruneOnnxRuntime(resolve(preparedPublicDir, "wake-word/ort"));
  await rm(resolve(preparedPublicDir, "data/i18n"), {
    recursive: true,
    force: true,
  });
  await pruneMarketingPages(resolve(preparedNextDir, "server/app"));
}

async function main() {
  console.log("Preparing Next.js standalone for electron-builder...");

  if (!existsSync(standaloneDir)) {
    throw new Error(
      `Standalone directory does not exist: ${standaloneDir}. Run 'nx build web' first.`,
    );
  }

  const appRoot = findAppRoot();
  const nodeModulesSrc = findNodeModules(appRoot);
  console.log(`App root:     ${appRoot}`);
  console.log(`node_modules: ${nodeModulesSrc}`);
  console.log(`To:           ${preparedDir}`);

  await rm(preparedDir, { recursive: true, force: true });
  await mkdir(preparedDir, { recursive: true });

  // Copy the app root WITHOUT its node_modules (which may be a symlink), then
  // overlay the real traced node_modules separately — exactly what the rsync
  // pipeline used to do.
  const appNodeModules = resolve(appRoot, "node_modules") + sep;
  await cp(appRoot, preparedDir, {
    ...copyOpts,
    filter: (src) =>
      src !== resolve(appRoot, "node_modules") &&
      !src.startsWith(appNodeModules),
  });
  await cp(nodeModulesSrc, resolve(preparedDir, "node_modules"), copyOpts);

  await copyIfExists(staticDir, preparedStaticDir, ".next/static");
  await copyIfExists(publicDir, preparedPublicDir, "public");

  await prune();

  console.log(`Done! Prepared Next.js server at: ${preparedDir}`);
}

main().catch((error) => {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
