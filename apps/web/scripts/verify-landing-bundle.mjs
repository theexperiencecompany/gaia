#!/usr/bin/env node
/**
 * Fail the build when app-only code lands in a marketing page's eager bundle.
 *
 * Every landing page once shipped the chat send stack (dexie + the IndexedDB
 * chat store + the stream engine) through the post-OAuth toast, the PostHog SDK
 * through a static import, and the 200 KB OpenUI stylesheet through
 * globals.css. None of that shows up as a failure anywhere else: the pages
 * still render, only slower. Several of these pages render on their first
 * request, so there is no prerendered HTML to read. Instead this takes each
 * route's eager chunks from the build manifests, the same lists Next writes
 * into the page's <script>/<link> tags (the root main files plus every
 * segment's entry chunks and CSS), and reads the source maps of those chunks,
 * so it checks exactly what a visitor downloads before the page is interactive.
 *
 * Run after `next build` (needs productionBrowserSourceMaps):
 *   node scripts/verify-landing-bundle.mjs
 */
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_DIR = join(root, ".next");
const SERVER_APP_DIR = join(NEXT_DIR, "server", "app");

/** One page per landing route type, with the app route that renders it. */
const PAGES = [
  { url: "/en", route: "/[locale]/(landing)/page" },
  { url: "/en/pricing", route: "/[locale]/(landing)/pricing/page" },
  { url: "/en/compare/motion", route: "/[locale]/(landing)/compare/[slug]/page" },
  { url: "/en/for/consultants", route: "/[locale]/(landing)/for/[persona]/page" },
  { url: "/en/blog/why-open-source", route: "/[locale]/(landing)/blog/[slug]/page" },
];

/** Source-map paths that must never be in a landing page's eager scripts. */
const FORBIDDEN_SOURCES = [
  { label: "dexie", pattern: /node_modules\/(?:\.pnpm\/[^/]+\/node_modules\/)?dexie\// },
  { label: "posthog-js", pattern: /node_modules\/(?:\.pnpm\/[^/]+\/node_modules\/)?posthog-js\// },
  { label: "chat IndexedDB store", pattern: /apps\/web\/src\/lib\/db\// },
  { label: "chat stream engine", pattern: /apps\/web\/src\/features\/chat\/stream\// },
];

/** Selectors that must never be in a landing page's render-blocking CSS. */
// .openui-card is react-ui's own Card; GAIA's .openui-document rules for its editor are global on purpose.
const FORBIDDEN_CSS = [{ label: "OpenUI component styles", needle: ".openui-card" }];

const SOURCE_MAP_URL = /\/\/# sourceMappingURL=(\S+)\s*$/;

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function chunkSources(chunkPath) {
  const code = readFileSync(chunkPath, "utf8");
  const mapName = code.match(SOURCE_MAP_URL)?.[1];
  if (!mapName) throw new Error(`${chunkPath} has no sourceMappingURL`);
  const map = readJson(join(dirname(chunkPath), mapName));
  const sections = map.sections ? map.sections.map((section) => section.map) : [map];
  return sections.flatMap((section) => section.sources ?? []);
}

const require = createRequire(import.meta.url);

/** The route's client reference manifest, which lists each segment's entry JS and CSS. */
// Loaded the way Next's own build stats load it: the module assigns globalThis.__RSC_MANIFEST.
function routeManifest(route) {
  const manifestPath = join(SERVER_APP_DIR, `${route}_client-reference-manifest.js`);
  if (!existsSync(manifestPath)) return null;
  require(manifestPath);
  return globalThis.__RSC_MANIFEST?.[route] ?? null;
}

/** One line per page and offender, naming the first chunk that carries it. */
const failures = new Map();
function fail(url, label, detail) {
  const key = `${url}: ${label}`;
  if (!failures.has(key)) failures.set(key, `${key} (${detail})`);
}

// The chunks every app page boots with, ahead of its own segments' entries.
const { rootMainFiles } = readJson(join(NEXT_DIR, "build-manifest.json"));

for (const { url, route } of PAGES) {
  const manifest = routeManifest(route);
  if (!manifest) {
    fail(url, "no client reference manifest", route);
    continue;
  }
  const entryScripts = Object.values(manifest.entryJSFiles).flat();
  const styles = new Set(
    Object.values(manifest.entryCSSFiles)
      .flat()
      .map((style) => style.path),
  );
  if (entryScripts.length === 0) fail(url, "no route entry scripts found", route);

  for (const script of new Set([...rootMainFiles, ...entryScripts])) {
    for (const source of chunkSources(join(NEXT_DIR, script))) {
      for (const { label, pattern } of FORBIDDEN_SOURCES) {
        if (pattern.test(source)) fail(url, label, `${script}: ${source}`);
      }
    }
  }
  for (const style of styles) {
    const css = readFileSync(join(NEXT_DIR, style), "utf8");
    for (const { label, needle } of FORBIDDEN_CSS) {
      if (css.includes(needle)) fail(url, label, style);
    }
  }
}

if (failures.size > 0) {
  console.error(
    `[verify-landing-bundle] ${failures.size} landing bundle check(s) failed:\n${[...failures.values()].map((f) => `  - ${f}`).join("\n")}`,
  );
  process.exit(1);
}
console.log(
  `[verify-landing-bundle] ${PAGES.length} landing pages load no chat stack, PostHog SDK or OpenUI CSS eagerly.`,
);
