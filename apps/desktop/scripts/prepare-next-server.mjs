#!/usr/bin/env node
/**
 * Cross-platform Next.js standalone preparation for electron-builder — the one
 * prepare script for every platform (a shell variant once drifted and shipped
 * Windows without the prune + wake-word canary). Locates the standalone app root
 * (handles git worktree's nested layout), copies it, prunes dead weight, and asserts the canary.
 */

import { spawn } from "node:child_process";
import {
  existsSync,
  lstatSync,
  readdirSync,
  readlinkSync,
  realpathSync,
} from "node:fs";
import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
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

// Preserve symlinks VERBATIM (dereference: false + verbatimSymlinks: true).
// Next's standalone output is a self-contained pnpm tree whose module resolution
// depends on relative symlinks (apps/web/node_modules/next ->
// ../../../node_modules/.pnpm/next@…/node_modules/next, and each package's
// sibling deps inside .pnpm). Two footguns to avoid, both of which ship an app
// whose embedded server dies on boot with MODULE_NOT_FOUND (blank window after
// the splash timeout):
//   1. dereference: true flattens the tree, severing `next` from its own
//      dependencies (@next/env, postcss, styled-jsx, @swc/helpers, …). This was
//      harmless under pnpm's old hoisted linker (flat tree) and broke when
//      hoisting was dropped.
//   2. dereference: false alone still rewrites RELATIVE links to ABSOLUTE ones
//      pointing back into the build dir (fs.cp defaults verbatimSymlinks: false),
//      which dangle on the user's machine. verbatimSymlinks: true copies the
//      link target string as-is, keeping the tree relative and self-contained.
// The boot canary below starts the real server and fails the build if resolution
// is broken.
const copyOpts = {
  recursive: true,
  dereference: false,
  verbatimSymlinks: true,
  force: true,
};

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

// onnxruntime-web files the wake-word engine actually loads: the CPU "wasm"
// provider only (JSEP alone is 25 MiB, over Cloudflare Workers' per-asset cap).
// Keep in lockstep with RUNTIME_FILES in apps/web/scripts/sync-wake-word-runtime.mjs.
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

/**
 * Assert every symlink in the prepared tree resolves to a path INSIDE it. A
 * symlink that escapes to the build directory — absolute, or a relative chain
 * that climbs out — resolves fine on the build machine (so the boot canary
 * below would falsely pass) but dangles on the user's machine, producing the
 * exact MODULE_NOT_FOUND blank-window failure. Runs before the canary so the
 * canary's success is trustworthy.
 */
function assertSelfContained(root) {
  const rootReal = realpathSync(root);
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = resolve(dir, entry.name);
      if (entry.isSymbolicLink()) {
        let target;
        try {
          target = realpathSync(full);
        } catch {
          throw new Error(
            `Dangling symlink in prepared server: ${full} -> ${readlinkSync(full)}`,
          );
        }
        if (target !== rootReal && !target.startsWith(rootReal + sep)) {
          throw new Error(
            `Symlink escapes the prepared server bundle: ${full} -> ${target}. ` +
              "It would dangle on the user's machine (blank window / MODULE_NOT_FOUND).",
          );
        }
      } else if (entry.isDirectory()) {
        walk(full);
      }
    }
  };
  walk(root);
  console.log("Self-containment check: all symlinks resolve inside the bundle.");
}

/** Bind an OS-assigned free port, then release it for the canary to reuse. */
function getFreePort() {
  return new Promise((resolvePort, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolvePort(port));
    });
  });
}

/**
 * Boot the prepared standalone server the way the desktop runtime does and
 * assert it reaches "Ready". A green `next build` does NOT prove the standalone
 * server can start: Next's file tracer has silently dropped a runtime
 * dependency of `next` before (`@swc/helpers` under pnpm's isolated linker),
 * shipping an app whose embedded server died on boot with MODULE_NOT_FOUND —
 * the user saw only a blank window after the splash timeout. This canary starts
 * the real server and fails the packaging build loudly if it cannot, so a
 * broken bundle can never ship again. Readiness detection mirrors the runtime
 * (`src/main/server.ts`).
 */
async function assertServerBoots() {
  const serverPath = resolve(preparedDir, SERVER_ENTRY);
  const port = await getFreePort();
  console.log(`Boot canary: starting standalone server on port ${port}...`);

  const child = spawn(process.execPath, [serverPath], {
    cwd: preparedDir,
    env: { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1", NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  const BOOT_TIMEOUT_MS = 60_000;
  const stderr = [];

  const outcome = await new Promise((settleOutcome) => {
    let settled = false;
    const settle = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      settleOutcome(result);
    };

    let stdoutBuffer = "";
    child.stdout.on("data", (buf) => {
      const text = buf.toString();
      process.stdout.write(`[canary] ${text}`);
      // A chunk boundary can split the readiness token across two data
      // events — keep a bounded rolling buffer so the match sees the join.
      stdoutBuffer = (stdoutBuffer + text).slice(-1024);
      if (/Ready|started server/i.test(stdoutBuffer)) settle({ ok: true });
    });
    child.stderr.on("data", (buf) => {
      stderr.push(buf.toString());
      process.stderr.write(`[canary] ${buf}`);
    });
    child.on("exit", (code) =>
      settle({ ok: false, reason: `server exited with code ${code} before becoming ready` }),
    );
    child.on("error", (err) =>
      settle({ ok: false, reason: `failed to spawn server: ${err.message}` }),
    );

    const timer = setTimeout(
      () => settle({ ok: false, reason: `server did not report ready within ${BOOT_TIMEOUT_MS}ms` }),
      BOOT_TIMEOUT_MS,
    );
  });

  if (child.exitCode === null) {
    child.kill("SIGTERM");
    // Force-kill if SIGTERM is ignored. unref()'d so it never keeps the build
    // process alive past the child; cleared once the child actually exits.
    const killTimer = setTimeout(() => {
      if (child.pid) {
        try {
          process.kill(child.pid, "SIGKILL");
        } catch {
          // Already exited.
        }
      }
    }, 3000);
    killTimer.unref();
    child.once("exit", () => clearTimeout(killTimer));
  }

  if (!outcome.ok) {
    throw new Error(
      `Boot canary failed: ${outcome.reason}. The prepared Next.js standalone server ` +
        `cannot start, so the packaged desktop app would show a blank window.` +
        (stderr.length ? `\n--- server stderr ---\n${stderr.join("")}` : ""),
    );
  }
  console.log("Boot canary: standalone server booted successfully.");
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

  assertSelfContained(preparedDir);
  await assertServerBoots();

  console.log(`Done! Prepared Next.js server at: ${preparedDir}`);
}

main().catch((error) => {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
