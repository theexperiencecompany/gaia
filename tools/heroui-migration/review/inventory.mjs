#!/usr/bin/env node
/**
 * The route inventory: every page.tsx under apps/web/src/app, in every route
 * group, bound to concrete URLs. Nothing is hand-listed: static routes come from
 * the file tree, marketing dynamic segments from the build's prerender manifest
 * (so they name real content), and app dynamic segments from the seed.
 *
 *   node review/inventory.mjs --tree ~/v3review/before --out ~/v3review/out
 *
 * Writes <out>/inventory.json: { targets: [...], skipped: [...] }. A page that
 * cannot be bound is listed in `skipped` with the reason; the run fails if any
 * page.tsx is neither bound nor skipped.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { DEFAULT_OUT } from "./config.mjs";

const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const TREE = resolve(arg("tree", "."));
const OUT = resolve(arg("out", DEFAULT_OUT));
const APP = join(TREE, "apps/web/src/app");
const WEB = join(TREE, "apps/web");

const seed = JSON.parse(readFileSync(join(OUT, "seed-state.json"), "utf8"));
const manifestPath = join(WEB, ".next/prerender-manifest.json");
if (!existsSync(manifestPath)) throw new Error(`no ${manifestPath}: build the before tree first (stack.sh build before)`);
const prerendered = Object.keys(JSON.parse(readFileSync(manifestPath, "utf8")).routes)
  .map((p) => p.replace(/^\/en(?=\/|$)/, "") || "/")
  .sort();

function pages(dir) {
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) out.push(...pages(p));
    else if (e.name === "page.tsx" || e.name === "page.dev.tsx") out.push(p);
  }
  return out;
}

/** "[locale]/(landing)/learn/[term]/page.tsx" -> { group: "landing", pattern: "/learn/[term]" } */
function parse(file) {
  const segs = relative(APP, file).split("/").slice(0, -1);
  const group = segs.find((s) => /^\(.*\)$/.test(s))?.slice(1, -1) ?? (segs[0] === "[locale]" ? "root" : "outside-locale");
  const pattern = "/" + segs.filter((s) => s !== "[locale]" && !/^\(.*\)$/.test(s)).join("/");
  return { group, pattern, file: relative(TREE, file), dev: file.endsWith("page.dev.tsx") };
}

/** First prerendered default-locale path matching a dynamic pattern: real content, chosen deterministically; null if none. */
function firstPrerendered(pattern) {
  const re = new RegExp("^" + pattern.replace(/\[[^\]]+\]/g, "[^/]+") + "$");
  return prerendered.find((p) => re.test(p) && !STATIC_PATTERNS.has(p)) ?? null;
}

const ALL_PAGES = pages(APP).sort().map((file) => ({ file, ...parse(file) }));
/** A static route also matches a sibling dynamic pattern (/blog/create vs /blog/[slug]); it is not an instance of it. */
const STATIC_PATTERNS = new Set(ALL_PAGES.filter((p) => !p.pattern.includes("[")).map((p) => p.pattern));

const SETTINGS_SECTIONS = (() => {
  const src = readFileSync(join(WEB, "src/features/settings/config/sectionKeys.ts"), "utf8");
  const body = src.match(/VALID_SECTIONS = \[([\s\S]*?)\]/)?.[1];
  if (!body) throw new Error("could not read VALID_SECTIONS from sectionKeys.ts");
  return [...body.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
})();

const AREA_RULES = [
  [/^\/c(\/|$)/, "chat"],
  [/^\/pins/, "chat"],
  [/^\/todos/, "todos"],
  [/^\/calendar/, "calendar"],
  [/^\/workflows/, "workflows"],
  [/^\/settings/, "settings"],
  [/^\/(onboarding|setup)/, "onboarding"],
  [/^\/(desktop-popup|wake-listener)/, "desktop popup"],
  [/^\/(login|signup|desktop-login|auth|redirect|connect$)/, "auth"],
];
const areaOf = (pattern, group) =>
  AREA_RULES.find(([re]) => re.test(pattern))?.[1] ?? (group === "main" ? "app" : "marketing");

/** Who the browser is: anon gets a 401 from the bypass (logged out), the others are seeded users. */
function userOf(pattern, group) {
  if (/^\/onboarding/.test(pattern)) return "onboarding";
  if (group === "main" || group === "desktop" || group === "live") return "review";
  if (/^\/(desktop-login|payment\/success|profile)/.test(pattern)) return "review";
  return "anon";
}

const SKIP = {
  "/live/[code]": "needs a live browser-session share code and token minted by a running browser task; there is no seedable session",
};

const BINDERS = {
  "/c/[id]": () => Object.entries(seed.conversations).map(([k, id]) => ({ url: `/c/${id}`, label: `chat: ${k}` })),
  "/settings/[section]": () => SETTINGS_SECTIONS.map((s) => ({ url: `/settings/${s}`, label: `settings: ${s}` })),
  "/todos/label/[label]": () => [{ url: "/todos/label/design", label: "todos: label design" }],
  "/todos/priority/[priority]": () => [{ url: "/todos/priority/high", label: "todos: high priority" }],
  "/todos/project/[projectId]": () => [{ url: `/todos/project/${seed.projects.work}`, label: "todos: project Work" }],
  "/workflows/[id]": () => [{ url: `/workflows/${seed.workflows.digest}`, label: "workflow: morning digest" }],
  "/use-cases/[slug]": () => [{ url: `/use-cases/${seed.useCaseSlug}`, label: "use case: seeded public workflow" }],
  "/profile/[id]": () => [{ url: `/profile/${seed.users.review.id}`, label: "profile: review user" }],
};

const targets = [];
const skipped = [];
for (const { group, pattern, file: rel, dev } of ALL_PAGES) {
  if (dev) {
    skipped.push({ pattern, file: rel, reason: "page.dev.tsx: development-only page, not part of a production build" });
    continue;
  }
  if (SKIP[pattern]) {
    skipped.push({ pattern, file: rel, reason: SKIP[pattern] });
    continue;
  }
  const area = areaOf(pattern, group);
  const user = userOf(pattern, group);
  let bound;
  if (BINDERS[pattern]) bound = BINDERS[pattern]();
  else if (/\[/.test(pattern)) {
    const url = firstPrerendered(pattern);
    if (!url) {
      skipped.push({ pattern, file: rel, reason: "the before build prerendered no instance of it (its content source, the seeded local API, has too little data for this page to exist)" });
      continue;
    }
    bound = [{ url, label: `${pattern} (first prerendered)` }];
  }
  else bound = [{ url: pattern, label: pattern }];
  for (const b of bound) targets.push({ key: b.url, url: b.url, label: b.label, pattern, group, area, user, file: rel });
}

// Variants that a bare URL does not reach.
targets.push({
  key: "/settings/devices/approve?code",
  url: "/settings/devices/approve?code=KQ7M-2XPD",
  label: "device approval with a code",
  pattern: "/settings/devices/approve",
  group: "main",
  area: "settings",
  user: "review",
  file: "apps/web/src/app/[locale]/(main)/settings/devices/approve/page.tsx",
});

const keys = new Set();
for (const t of targets) {
  if (keys.has(t.key)) throw new Error(`duplicate target key ${t.key}`);
  keys.add(t.key);
}
writeFileSync(join(OUT, "inventory.json"), JSON.stringify({ tree: TREE, generatedAt: seed.seededAt, targets, skipped }, null, 2));
const byArea = Object.groupBy(targets, (t) => t.area);
console.log(`${targets.length} targets, ${skipped.length} skipped -> ${join(OUT, "inventory.json")}`);
for (const [a, ts] of Object.entries(byArea)) console.log(`  ${a.padEnd(14)} ${ts.length}`);
for (const s of skipped) console.log(`  skip ${s.pattern}: ${s.reason}`);
