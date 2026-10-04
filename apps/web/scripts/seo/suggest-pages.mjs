#!/usr/bin/env node
/**
 * suggest-pages.mjs: code-driven SEO loop, step 2 — turn GSC queries into pages.
 *
 * Reads public/data/seo/queries.json (from pull-gsc.mjs) + existing slugs from
 *   public/data/{comparisons,alternatives,combos,personas,glossary}/_slugs.json
 * and writes scripts/seo/suggestions.md — top 30 missing opportunities where:
 *   impressions > 50, position 5..30, and no existing page matches the query.
 *
 * Each opportunity is mapped to an existing template route:
 *   /compare/[slug] | /alternative-to/[slug] | /automate/[combo] | /learn/[term]
 *
 * Priority is a heuristic from GSC numbers ONLY (no hallucinated search volume):
 *   score = impressions * (31 - position) / 26   (more impr + closer to p1 = higher)
 *   High = top third of scores, Medium = middle, Low = bottom.
 *
 * Usage:
 *   node scripts/seo/suggest-pages.mjs
 *   node scripts/seo/suggest-pages.mjs --dry-run   # SAMPLE queries, no queries.json needed
 *   node scripts/seo/suggest-pages.mjs --in <file> --out <file>
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const argv = process.argv.slice(2);
const DRY_RUN = argv.includes("--dry-run");

function flagValue(name, fallback) {
  const prefix = `${name}=`;
  for (const a of argv) if (a.startsWith(prefix)) return a.slice(prefix.length);
  return fallback;
}

const IN = flagValue("--in", join(root, "public/data/seo/queries.json"));
const OUT = flagValue("--out", join(root, "scripts/seo/suggestions.md"));

const FEATURES = ["comparisons", "alternatives", "combos", "personas", "glossary"];

// Standalone landing pages that also satisfy query intent (would cannibalise
// a new programmatic page). Kept in sync with UNTRANSLATED_STATIC_PAGES in
// src/lib/sitemapData.ts.
const STATIC_SLUGS = ["open-source-ai-assistant", "ai-chief-of-staff", "inbox-zero-ai"];

function loadSlugs(feature) {
  const p = join(root, "public/data", feature, "_slugs.json");
  if (!existsSync(p)) return [];
  try {
    const v = JSON.parse(readFileSync(p, "utf8"));
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function slugify(s) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
}

function normalizeQuery(s) {
  return s.toLowerCase().trim().replace(/\s+/g, " ");
}

// A page "covers" a query if any existing slug matches the query slug exactly,
// or the de-hyphenated slug appears as a whole phrase inside the query.
function findCoveringPage(query, slugIndex) {
  const q = normalizeQuery(query);
  const qSlug = slugify(q);
  for (const { feature, slug } of slugIndex) {
    if (qSlug === slug) return { feature, slug };
    const phrase = slug.replace(/-/g, " ");
    const re = new RegExp(`(^|[^a-z0-9])${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`);
    if (re.test(q)) return { feature, slug };
  }
  return null;
}

// Map a query to the closest existing template route.
function mapToTemplate(query) {
  const q = normalizeQuery(query);
  const has = (...words) => words.some((w) => q.includes(w));

  // 1. Head-to-head → /compare/[opponent]
  const vsMatch = q.match(/(.+?)\s+vs\.?\s+(.+)|(.*?)\s+versus\s+(.+)/);
  if (vsMatch) {
    const parts = vsMatch.slice(1).filter(Boolean).map((s) => s.trim());
    const opponent = parts.find((p) => !/^(gaia|heygaia|hey gaia)\b/.test(p)) ?? parts[0];
    const slug = slugify(opponent.replace(/^(gaia|heygaia)\s*(ai)?\s*/, "").replace(/\s*(ai|app|tool)$/, "")) || "general";
    return { template: "/compare/[slug]", path: `/compare/${slug}`, reason: "head-to-head 'vs' query" };
  }
  // 2. Replacement intent → /alternative-to/[tool]
  if (has("alternative", "instead of", "replace", "switch from", "migrate from", "like ") && !has("integrat", "connect", "sync", "automate")) {
    const m = q.match(/alternative\s+to\s+([a-z0-9 .+-]+)/) ?? q.match(/([a-z0-9][a-z0-9 .+-]+?)\s+alternative/) ?? q.match(/replace\s+([a-z0-9 .+-]+)/);
    const tool = (m?.[1] ?? q.replace(/^(best|top|free)\s+/, "").split(/\s+(alternative|app|tool|ai)\b/)[0]).trim();
    const slug = slugify(tool) || "general";
    return { template: "/alternative-to/[slug]", path: `/alternative-to/${slug}`, reason: "replacement intent" };
  }
  // 3. Integration / automation intent → /automate/[combo]
  if (has("automat", "integrat", "connect", "sync", "workflow", " + ", " with ", " to slack", " to notion", "gmail", "zapier")) {
    const known = ["gmail", "slack", "notion", "todoist", "linear", "asana", "github", "google-calendar", "google calendar", "jira", "clickup", "trello", "hubspot", "zoom", "discord", "drive", "figma", "salesforce", "airtable", "stripe", "teams", "loom", "superhuman", "spark"];
    const found = [...new Set(known.filter((t) => q.includes(t)).map((t) => slugify(t)))];
    let combo = "general";
    if (found.length >= 2) combo = [...found.slice(0, 2)].sort().join("-");
    else if (found.length === 1) combo = [found[0], "notion"].sort().join("-");
    // Note: order variants canonicalise via canonicalSlug in combosData.ts
    // (e.g. github-slack → slack-github), so either order is a valid suggestion.
    return { template: "/automate/[combo]", path: `/automate/${combo}`, reason: "integration/automation intent" };
  }
  // 4. Everything informational → /learn/[term]
  const term = slugify(q.replace(/^(what is|what are|what's|how to|guide to|learn|tutorial:?|meaning of|definition of)\s+/, "").split(/\b(for|vs|alternative|app|tool|software|review)\b/)[0].trim()) || "general";
  return { template: "/learn/[term]", path: `/learn/${term.slice(0, 60)}`, reason: "informational query" };
}

function priorityOf(score, breaks) {
  if (score >= breaks.hi) return "High";
  if (score >= breaks.lo) return "Medium";
  return "Low";
}

// ---- load queries ----
let meta = { sample: false };
let rows = [];
if (DRY_RUN && existsSync(IN)) {
  // Prefer the real pipeline output when it exists (pull-gsc --dry-run first),
  // so fixtures live in exactly one place.
  const payload = JSON.parse(readFileSync(IN, "utf8"));
  meta = payload.meta ?? { sample: true };
  rows = payload.rows ?? [];
} else if (DRY_RUN) {
  meta = { sample: true, note: "SAMPLE DATA — --dry-run fallback fixtures, not real GSC numbers." };
  rows = [
    { query: "gaia vs routine", clicks: 21, impressions: 880, ctr: 0.0239, position: 11.5 },
    { query: "timehero alternative", clicks: 9, impressions: 640, ctr: 0.0141, position: 14.8 },
    { query: "connect superhuman to gmail automatically", clicks: 5, impressions: 450, ctr: 0.0111, position: 22.6 },
    { query: "what is timeboxing", clicks: 17, impressions: 1900, ctr: 0.0089, position: 20.3 },
  ];
} else {
  if (!existsSync(IN)) {
    console.error(`[suggest-pages] missing ${IN}. Run pull-gsc.mjs first, or use --dry-run for SAMPLE data.`);
    process.exit(1);
  }
  const payload = JSON.parse(readFileSync(IN, "utf8"));
  meta = payload.meta ?? {};
  rows = payload.rows ?? [];
}

// ---- load existing coverage ----
const slugIndex = [];
for (const feature of FEATURES) {
  for (const slug of loadSlugs(feature)) slugIndex.push({ feature, slug });
}
for (const slug of STATIC_SLUGS) slugIndex.push({ feature: "static", slug });
const counts = Object.fromEntries(FEATURES.map((f) => [f, loadSlugs(f).length]));
const slugSets = Object.fromEntries(
  FEATURES.map((f) => [f, new Set(loadSlugs(f))]),
);

// Combo slugs are toolA-toolB pairs; the same pair in reverse order is the same
// page (canonicalSlug in combosData.ts). Try every split point so we catch
// e.g. suggested "linear-slack" when "slack-linear" already exists.
function comboExists(slug) {
  if (slugSets.combos.has(slug)) return true;
  const parts = slug.split("-");
  for (let i = 1; i < parts.length; i++) {
    const flipped = [...parts.slice(i), ...parts.slice(0, i)].join("-");
    if (slugSets.combos.has(flipped)) return true;
  }
  return false;
}

// Loop closure: the mapped suggestion itself must not already exist,
// otherwise the query is covered even when no slug phrase matched it
// (e.g. "automate gmail + slack" → /automate/gmail-slack exists).
function suggestionExists(mapped) {
  const slug = mapped.path.split("/").pop() ?? "";
  switch (mapped.template) {
    case "/compare/[slug]":
      return slugSets.comparisons.has(slug);
    case "/alternative-to/[slug]":
      return slugSets.alternatives.has(slug);
    case "/automate/[combo]":
      return comboExists(slug);
    case "/learn/[term]":
      return slugSets.glossary.has(slug) || STATIC_SLUGS.includes(slug);
    default:
      return false;
  }
}

// ---- filter: striking distance, uncovered ----
const scored = [];
let covered = 0;
let outOfRange = 0;
for (const r of rows) {
  if (!(r.impressions > 50) || !(r.position >= 5 && r.position <= 30)) {
    outOfRange++;
    continue;
  }
  const cover = findCoveringPage(r.query, slugIndex);
  if (cover) {
    covered++;
    continue;
  }
  const mapped = mapToTemplate(r.query);
  if (suggestionExists(mapped)) {
    covered++;
    continue;
  }
  const score = (r.impressions * (31 - r.position)) / 26;
  scored.push({ ...r, ...mapped, score });
}
scored.sort((a, b) => b.score - a.score);
const top = scored.slice(0, 30);

let breaks = { hi: 0, lo: 0 };
if (scored.length > 0) {
  const sorted = [...scored].map((s) => s.score).sort((a, b) => a - b);
  breaks = {
    hi: sorted[Math.floor(sorted.length * 0.66)] ?? 0,
    lo: sorted[Math.floor(sorted.length * 0.33)] ?? 0,
  };
}

const today = new Date().toISOString().slice(0, 10);
const sampleBanner = meta.sample
  ? "> **SAMPLE DATA** — generated with `--dry-run`. All queries/impressions/positions below are fixtures, not real GSC numbers.\n\n"
  : `> Source: GSC property \`${meta.property ?? "n/a"}\`, ${meta.startDate ?? "?"}..${meta.endDate ?? "?"} (pulled ${meta.generatedAt ?? "?"}).\n\n`;

let md = `# SEO page suggestions — ${today}\n\n${sampleBanner}`;
md += `## Inputs\n\n`;
md += `- Queries scanned: **${rows.length}** (impressions>50 + position 5–30: **${scored.length}** uncovered, ${covered} already covered, ${outOfRange} out of range)\n`;
md += `- Existing pages: ${FEATURES.map((f) => `${f} ${counts[f]}`).join(" · ")} + ${STATIC_SLUGS.length} static landing pages\n`;
md += `- Priority heuristic (GSC numbers only, no invented search volume): \`score = impressions × (31 − position) / 26\` → High ≥ ${breaks.hi.toFixed(1)}, Medium ≥ ${breaks.lo.toFixed(1)}, else Low\n\n`;
md += `## Top ${top.length} missing opportunities\n\n`;
md += `| # | Query | Clicks | Impr | CTR | Pos | Suggested path | Template | Priority | Why |\n`;
md += `| - | ----- | ------ | ---- | --- | --- | -------------- | -------- | -------- | --- |\n`;
top.forEach((s, i) => {
  const pri = priorityOf(s.score, breaks);
  const ctr = typeof s.ctr === "number" ? (s.ctr * 100).toFixed(2) + "%" : String(s.ctr);
  const q = s.query.replace(/\|/g, "\\|");
  md += `| ${i + 1} | ${q} | ${s.clicks} | ${s.impressions} | ${ctr} | ${Number(s.position).toFixed(1)} | \`${s.path}\` | \`${s.template}\` | ${pri} | ${s.reason}; score ${s.score.toFixed(1)} |\n`;
});
if (top.length === 0) md += `\n_No uncovered striking-distance queries — nothing to suggest._\n`;
md += `\n## Next step\n\nPick the top High-priority rows and create the page under the suggested template (content already has per-slug JSON + getters). Re-run \`seo:pull-gsc\` weekly and diff this file to track coverage.\n`;

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, md);
console.log(`[suggest-pages]${DRY_RUN ? " --dry-run (SAMPLE)" : ""}: scanned ${rows.length} queries, ${covered} covered, ${outOfRange} out of range → ${top.length} suggestions -> ${OUT}`);
