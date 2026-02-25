#!/usr/bin/env node
/**
 * Cross-platform Next.js standalone preparation for desktop packaging.
 *
 * Copies `apps/web/.next/standalone` into `apps/desktop/.next-server-prepared`
 * with dereferenced symlinks, then overlays static/public assets required at runtime.
 * This avoids shell/rsync dependencies for Windows CI runners.
 */

import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(scriptDir, "../../web");
const standaloneDir = resolve(webDir, ".next/standalone");
const staticDir = resolve(webDir, ".next/static");
const publicDir = resolve(webDir, "public");
const preparedDir = resolve(scriptDir, "../.next-server-prepared");
const preparedStaticDir = resolve(preparedDir, "apps/web/.next/static");
const preparedPublicDir = resolve(preparedDir, "apps/web/public");

const copyOpts = {
  recursive: true,
  dereference: true,
  force: true,
};

async function copyIfExists(src, dest, label) {
  if (!existsSync(src)) {
    console.warn(`[warn] Skipping missing ${label}: ${src}`);
    return;
  }
  await mkdir(dest, { recursive: true });
  await cp(src, dest, copyOpts);
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

  console.log(`Done! Prepared Next.js server at: ${preparedDir}`);
}

main().catch((error) => {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
