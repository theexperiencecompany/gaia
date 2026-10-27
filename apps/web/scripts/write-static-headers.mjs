#!/usr/bin/env node
/**
 * Write the Workers Static Assets _headers: the checked-in cache rules (public/_headers) plus the security headers from security-headers.mjs.
 * Static assets never reach the worker, so without this the promoted landing HTML and public/ files ship with none of next.config.mjs headers().
 * Run after `opennextjs-cloudflare build` (which copies public/_headers into .open-next/assets), alongside promote-static.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderStaticHeaders } from "../security-headers.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const ASSETS_DIR = join(root, ".open-next/assets");

if (!existsSync(ASSETS_DIR)) {
  console.error(`[write-static-headers] assets dir missing: ${ASSETS_DIR} — run the build first.`);
  process.exit(1);
}

const cacheRules = readFileSync(join(root, "public/_headers"), "utf8");
writeFileSync(join(ASSETS_DIR, "_headers"), renderStaticHeaders(cacheRules));
console.log("[write-static-headers] wrote security headers into .open-next/assets/_headers.");
