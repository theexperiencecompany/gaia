#!/usr/bin/env node
/**
 * Promote prerendered landing HTML into Workers Static Assets so Cloudflare serves it from the edge without invoking the OpenNext worker (worker-served HTML pays ~1.5s cold-start on a cold isolate vs ~0.05–0.25s cold-immune for Workers Assets).
 * Run after `opennextjs-cloudflare build`, before `wrangler deploy`: opennextjs-cloudflare build && node scripts/promote-static-landing.mjs && wrangler deploy.
 * Excludes i18n locale-detection routes (learn/automate/compare/alternative-to/for — redirect on Accept-Language, must keep running the worker), auth routes (login/signup/desktop-login — keep server logic), and all (main) app routes (never touched here).
 */
import { existsSync, readdirSync, mkdirSync, copyFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const LANDING_DIR = join(root, "src/app/[locale]/(landing)");
const PRERENDER_DIR = join(root, ".next/server/app/en"); // default locale (en) — no URL prefix
const HOME_HTML = join(root, ".next/server/app/en.html");
const ASSETS_DIR = join(root, ".open-next/assets");

// Routes that must keep the worker (locale detection / auth).
const EXCLUDE = new Set([
  "learn", "automate", "compare", "alternative-to", "for", // next-intl detection routes
  "login", "signup", "desktop-login", // auth
]);

if (!existsSync(ASSETS_DIR)) {
  console.error(`[promote-static] assets dir missing: ${ASSETS_DIR} — run the build first.`);
  process.exit(1);
}

// Source of truth: the (landing) route group dictates what is a marketing page.
const landingRoutes = readdirSync(LANDING_DIR, { withFileTypes: true })
  .filter((d) => d.isDirectory() && !d.name.startsWith("[") && !d.name.startsWith("("))
  .map((d) => d.name)
  .filter((name) => !EXCLUDE.has(name));

let promoted = 0;
const skipped = [];

// Homepage: en.html -> index.html (served at "/").
if (existsSync(HOME_HTML)) {
  copyFileSync(HOME_HTML, join(ASSETS_DIR, "index.html"));
  promoted++;
} else {
  skipped.push("<home> (en.html missing)");
}

for (const route of landingRoutes) {
  const src = join(PRERENDER_DIR, `${route}.html`);
  if (!existsSync(src) || !statSync(src).isFile()) {
    skipped.push(`${route} (no static prerender — dynamic/ISR, left on worker)`);
    continue;
  }
  const dest = join(ASSETS_DIR, `${route}.html`);
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
  promoted++;
}

console.log(`[promote-static] promoted ${promoted} landing page(s) to static assets.`);
if (skipped.length) console.log(`[promote-static] left on worker: ${skipped.join(", ")}`);
