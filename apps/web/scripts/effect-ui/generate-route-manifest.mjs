#!/usr/bin/env node
/**
 * Regenerates apps/web/e2e/effect-ui/routes.generated.json from the App Router.
 *
 * One entry per page.tsx. Rerun after adding, removing, or porting a page:
 *
 *   node apps/web/scripts/effect-ui/generate-route-manifest.mjs
 *
 * The output is deterministic (sorted, no timestamps), so a rerun on unchanged
 * routes produces no diff and a diff in review means the route surface moved.
 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = join(HERE, "..", "..");
const APP_DIR = join(WEB_ROOT, "src", "app");
const EFFECT_PAGES_DIR = join(WEB_ROOT, "src", "components", "effect", "pages");
const DATA_DIR = join(WEB_ROOT, "public", "data");
const OUTPUT = join(WEB_ROOT, "e2e", "effect-ui", "routes.generated.json");

/**
 * A page is ported when it can serve the Effect UI build today. Three signals,
 * all text-level so the generator needs no TypeScript runtime:
 *   - the page branches on `?effect=1` (the migration's URL flag),
 *   - it imports one of the client adapters in src/components/effect/pages/,
 *   - it mounts EffectRoot / @heygaia/effect-ui itself.
 * A new port must use one of these shapes, or add a signal here.
 */
const ADAPTER_IMPORTS = readdirSync(EFFECT_PAGES_DIR, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".tsx"))
  .map((entry) => entry.name.slice(0, -".tsx".length))
  .map((name) => {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`@/components/effect/pages/${escaped}(?:\\.tsx)?["']`);
  });

const PORTED_SIGNALS = [
  /\beffect\s*===\s*["']1["']/,
  ...ADAPTER_IMPORTS,
  /@\/components\/effect\/EffectRoot|@heygaia\/effect-ui/,
];

/**
 * Sample values for dynamic segments. Keys are the route template, because the
 * same segment name means a different resource on different routes ([id] is a
 * conversation under /c and a holo card under /profile).
 *
 * Marketing slugs are read from public/data/<family>/_slugs.json, the source
 * those pages render from, so a content change cannot leave a stale sample.
 */
function dataSlugs(family) {
  const slugs = JSON.parse(
    readFileSync(join(DATA_DIR, family, "_slugs.json"), "utf8"),
  );
  if (slugs.length === 0) {
    throw new Error(`public/data/${family}/_slugs.json is empty`);
  }
  return slugs;
}

function firstDataSlug(family) {
  return dataSlugs(family)[0];
}

/** Every /automate/with/<app> page is a tool slug from the combo data. */
function firstComboApp() {
  const combo = JSON.parse(
    readFileSync(
      join(DATA_DIR, "combos", `${firstDataSlug("combos")}.json`),
      "utf8",
    ),
  );
  // comboApps.ts folds this alias onto the one app page it shares.
  return combo.toolASlug === "teams" ? "microsoft-teams" : combo.toolASlug;
}

const ROUTE_SAMPLES = new Map([
  ["/alternative-to/[slug]", { slug: firstDataSlug("alternatives") }],
  ["/automate/[combo]", { combo: firstDataSlug("combos") }],
  ["/automate/page/[page]", { page: "2" }],
  ["/automate/with/[app]", { app: firstComboApp() }],
  ["/blog/[slug]", { slug: firstDataSlug("blog") }],
  ["/compare/[slug]", { slug: firstDataSlug("comparisons") }],
  ["/compare/category/[category]", { category: "ai-assistants" }],
  ["/compare/page/[page]", { page: "2" }],
  // FEATURES in src/features/landing/data/features/aiIntelligence.ts.
  ["/features/[slug]", { slug: "smart-chat" }],
  ["/for/[persona]", { persona: "consultants" }],
  ["/learn/[term]", { term: firstDataSlug("glossary") }],
  // CATEGORY_LABEL_KEYS in src/features/glossary/data/glossaryCategories.ts.
  ["/learn/category/[category]", { category: "ai-concepts" }],
  ["/learn/page/[page]", { page: "2" }],
  ["/live/[code]", { code: "sample-code" }],
  ["/marketplace/page/[page]", { page: "2" }],
  // A public holo card id; an unknown one renders the page's "not found" state.
  ["/profile/[id]", { id: "sample-profile" }],
  // VALID_SECTIONS in src/features/settings/config/sectionKeys.ts.
  ["/settings/[section]", { section: "account" }],
  ["/todos/label/[label]", { label: "work" }],
  // Priority in libs/shared/ts/src/types/todo.ts.
  ["/todos/priority/[priority]", { priority: "high" }],
  // The page filters by id; an unknown project renders an empty list.
  ["/todos/project/[projectId]", { projectId: "sample-project" }],
  // Permanent-redirects to /workflows?id=<id>, so any id resolves.
  ["/workflows/[id]", { id: "sample-workflow" }],
]);

/**
 * Routes that cannot be given a resolving URL offline. A skip keeps the route
 * in the manifest, so the coverage report shows what is not exercised.
 */
const SKIP_REASONS = new Map([
  [
    "/c/[id]",
    "Conversation ids belong to the seeded dev user; /c covers the chat shell.",
  ],
  [
    "/marketplace/[slug]",
    "Slug list comes from the integrations API at request time.",
  ],
  [
    "/use-cases/[slug]",
    "Slug list comes from the workflows API at request time.",
  ],
]);

const ROUTE_GROUP = /^\(.+\)$/;
const DYNAMIC_SEGMENT = /^\[+(?:\.\.\.)?([^\]]+)\]+$/;

function* walkPages(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walkPages(full);
    } else if (entry.name === "page.tsx") {
      yield full;
    }
  }
}

function isPorted(pageFile) {
  const source = readFileSync(pageFile, "utf8");
  return PORTED_SIGNALS.some((signal) => signal.test(source));
}

/** A page file's route template, e.g. /todos/priority/[priority]. The locale
 * segment is dropped: e2e runs the default locale, which has no URL prefix. */
function describePage(pageFile) {
  const segments = relative(APP_DIR, pageFile).split(sep).slice(0, -1);
  const template = [];

  for (const segment of segments) {
    if (ROUTE_GROUP.test(segment) || segment === "[locale]") continue;
    const dynamic = DYNAMIC_SEGMENT.exec(segment);
    template.push(dynamic ? `[${dynamic[1]}]` : segment);
  }

  return { segments, template: `/${template.join("/")}` };
}

function resolvePath(route) {
  const skipReason = SKIP_REASONS.get(route.template);
  if (skipReason) {
    return { path: route.template, skip: true, reason: skipReason };
  }

  const samples = ROUTE_SAMPLES.get(route.template);
  if (!route.template.includes("[")) {
    return { path: route.template, skip: false, reason: null };
  }
  if (!samples) {
    const unresolved = route.template.match(/\[[^\]]+\]/g) ?? [];
    return {
      path: route.template,
      skip: true,
      reason: `No sample for ${unresolved.join(", ")}; add it to ROUTE_SAMPLES.`,
    };
  }

  const path = route.template.replace(/\[([^\]]+)\]/g, (segment, name) => {
    return samples[name] ?? segment;
  });

  return { path, skip: false, reason: null };
}

function buildManifest() {
  const routes = [];

  for (const pageFile of walkPages(APP_DIR)) {
    const route = describePage(pageFile);
    const desktopOnly = route.segments.includes("(desktop)");
    const resolved = desktopOnly
      ? {
          path: route.template,
          skip: true,
          reason: "Desktop-only Electron window; it renders no page chrome.",
        }
      : resolvePath(route);

    routes.push({
      path: resolved.path,
      file: relative(WEB_ROOT, pageFile),
      ported: isPorted(pageFile),
      skip: resolved.skip,
      reason: resolved.reason,
    });
  }

  return routes.sort((a, b) => a.path.localeCompare(b.path));
}

const manifest = buildManifest();
writeFileSync(OUTPUT, `${JSON.stringify(manifest, null, 2)}\n`);

const skipped = manifest.filter((route) => route.skip);
const ported = manifest.filter((route) => route.ported);
console.log(
  `wrote ${relative(WEB_ROOT, OUTPUT)}: ${manifest.length} routes, ` +
    `${manifest.length - skipped.length} runnable, ${ported.length} ported, ` +
    `${skipped.length} skipped`,
);
for (const route of skipped) {
  console.log(`  skip ${route.path}: ${route.reason}`);
}
