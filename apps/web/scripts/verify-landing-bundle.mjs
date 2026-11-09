#!/usr/bin/env node
/**
 * Fail the build when app-only code lands in a marketing page's eager bundle.
 *
 * Every landing page once shipped the chat send stack (dexie + the IndexedDB
 * chat store + the stream engine) through the post-OAuth toast, the PostHog SDK
 * through a static import, and the 200 KB OpenUI stylesheet through
 * globals.css. None of that shows up as a failure anywhere else: the pages
 * still render, only slower. This reads each prerendered page's own
 * <script>/<link> tags and the source maps of those chunks, so it checks
 * exactly what a visitor downloads before the page is interactive.
 *
 * Run after `next build` (needs productionBrowserSourceMaps):
 *   node scripts/verify-landing-bundle.mjs
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_DIR = join(root, ".next");
const PRERENDER_DIR = join(NEXT_DIR, "server", "app");

const PAGES = [
  "en",
  "en/pricing",
  "en/compare/motion",
  "en/for/consultants",
  "en/blog/why-open-source",
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

function staticFile(href) {
  return join(NEXT_DIR, href.replace(/^\/_next\//, ""));
}

function chunkSources(chunkPath) {
  const code = readFileSync(chunkPath, "utf8");
  const mapName = code.match(SOURCE_MAP_URL)?.[1];
  if (!mapName) throw new Error(`${chunkPath} has no sourceMappingURL`);
  const map = JSON.parse(readFileSync(join(dirname(chunkPath), mapName), "utf8"));
  const sections = map.sections ? map.sections.map((section) => section.map) : [map];
  return sections.flatMap((section) => section.sources ?? []);
}

/** One line per page and offender, naming the first chunk that carries it. */
const failures = new Map();
function fail(page, label, detail) {
  const key = `/${page}: ${label}`;
  if (!failures.has(key)) failures.set(key, `${key} (${detail})`);
}

for (const page of PAGES) {
  const htmlPath = join(PRERENDER_DIR, `${page}.html`);
  if (!existsSync(htmlPath)) {
    fail(page, "no prerendered HTML", htmlPath);
    continue;
  }
  const html = readFileSync(htmlPath, "utf8");
  // noModule scripts are Next's legacy-browser polyfills, which ship without a map.
  const scripts = new Set(
    [...html.matchAll(/<script[^>]+src="(\/_next\/static\/[^"]+\.js)"[^>]*>/g)]
      .filter((m) => !/noModule/i.test(m[0]))
      .map((m) => m[1]),
  );
  const styles = new Set(
    [...html.matchAll(/<link[^>]+href="(\/_next\/static\/[^"]+\.css)"/g)].map((m) => m[1]),
  );
  if (scripts.size === 0) fail(page, "no eager scripts found", htmlPath);

  for (const script of scripts) {
    for (const source of chunkSources(staticFile(script))) {
      for (const { label, pattern } of FORBIDDEN_SOURCES) {
        if (pattern.test(source)) fail(page, label, `${script}: ${source}`);
      }
    }
  }
  for (const style of styles) {
    const css = readFileSync(staticFile(style), "utf8");
    for (const { label, needle } of FORBIDDEN_CSS) {
      if (css.includes(needle)) fail(page, label, style);
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
