#!/usr/bin/env node
/**
 * Verify the OpenNext build output still carries usable prerenders for the
 * fully-static (`dynamicParams = false`) detail routes.
 *
 * Background: learn/compare/automate detail pages are `fallback: false`, so a
 * cold incremental cache makes the worker throw NoFallbackError and serve a
 * 404 it then caches. CI deploys never uploaded `.open-next/cache` to R2 (raw
 * `wrangler deploy` skips `populateCache`), which 404'd every detail page on
 * heygaia.io (alternative-to/for/use-cases survived — they render on demand).
 * The deploy workflow now runs `populateCache remote` before `wrangler deploy`,
 * which uploads WHATEVER is in `.open-next/cache` — including prerendered 404s
 * if build-time data loading ever breaks (a notFound() during prerender keeps
 * the build green). This script fails the build visibly before that poison can
 * ship: each spot-check path must be a complete prerender whose HTML carries
 * the entry's own metaTitle.
 *
 * Run after `opennextjs-cloudflare build`, before uploading the bundle:
 *   node scripts/verify-prerender-cache.mjs
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_DIR = join(root, ".next");
const OPEN_NEXT_CACHE_DIR = join(root, ".open-next", "cache");

// One spot-check per fallback:false route family, plus a fallback:true control.
// Markers come from the source JSON at check time — nothing hardcoded to rot.
const SPOT_CHECKS = [
  { urlPath: "en/learn/ical", dataFile: "glossary/ical.json" },
  { urlPath: "en/compare/hey-email", dataFile: "comparisons/hey-email.json" },
  { urlPath: "en/automate/slack-teams", dataFile: "combos/slack-teams.json" },
  { urlPath: "en/alternative-to/calendly", dataFile: "alternatives/calendly.json" },
];

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

const failures = [];

const manifestPath = join(NEXT_DIR, "prerender-manifest.json");
if (!existsSync(manifestPath)) {
  console.error(
    `[verify-prerender-cache] prerender manifest missing: ${manifestPath} — run next build first.`,
  );
  process.exit(1);
}
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const routes = manifest.routes ?? {};
const notFoundRoutes = new Set(manifest.notFoundRoutes ?? []);

// The build id scopes every cache key; there must be exactly one.
let buildId = null;
try {
  buildId = readFileSync(join(NEXT_DIR, "BUILD_ID"), "utf8").trim();
} catch {
  failures.push(".next/BUILD_ID unreadable");
}
const buildCacheDir = buildId ? join(OPEN_NEXT_CACHE_DIR, buildId) : null;
if (buildCacheDir && !existsSync(buildCacheDir)) {
  failures.push(`open-next cache dir missing for build ${buildId}`);
}

for (const { urlPath, dataFile } of SPOT_CHECKS) {
  const routeKey = `/${urlPath}`;
  const entry = routes[routeKey];
  if (!entry || entry.response !== "complete") {
    failures.push(
      `${routeKey}: not a complete prerender (missing from manifest routes or response=${entry?.response})`,
    );
    continue;
  }
  if (notFoundRoutes.has(routeKey)) {
    failures.push(`${routeKey}: prerendered as not-found at build time`);
    continue;
  }
  const source = JSON.parse(
    readFileSync(join(root, "public", "data", dataFile), "utf8"),
  );
  const marker = source.metaTitle;
  if (!marker) {
    failures.push(`${routeKey}: source ${dataFile} has no metaTitle to check against`);
    continue;
  }
  const cacheFile = buildCacheDir
    ? join(buildCacheDir, `${urlPath}.cache`)
    : null;
  if (!cacheFile || !existsSync(cacheFile)) {
    failures.push(`${routeKey}: cache entry missing (${cacheFile})`);
    continue;
  }
  const cached = JSON.parse(readFileSync(cacheFile, "utf8"));
  const html = cached.html ?? "";
  if (!html.includes(marker) && !html.includes(escapeHtml(marker))) {
    failures.push(
      `${routeKey}: cached HTML does not contain its metaTitle (${JSON.stringify(marker)}) — prerender likely 404'd at build time`,
    );
  }
}

if (failures.length > 0) {
  console.error(
    `[verify-prerender-cache] ${failures.length} prerender check(s) failed:\n${failures.map((f) => `  - ${f}`).join("\n")}`,
  );
  process.exit(1);
}
console.log(
  `[verify-prerender-cache] ${SPOT_CHECKS.length} detail prerenders verified (complete + titled).`,
);
