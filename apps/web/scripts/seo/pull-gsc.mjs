#!/usr/bin/env node
/**
 * pull-gsc.mjs: code-driven SEO loop, step 1 — pull real query data.
 *
 * Queries the Google Search Console Search Analytics API for the last 28d
 * (dimensions: query) and writes public/data/seo/queries.json:
 *   { meta: {...}, rows: [{ query, clicks, impressions, ctr, position }] }
 *
 * Auth: OAuth2 service-account JWT (server-to-server, no user consent).
 *   GSC_CLIENT_EMAIL  — service-account email (GSC property must add it as Viewer)
 *   GSC_PRIVATE_KEY   — PEM private key (escaped \n newlines are unescaped)
 *   GSC_PROPERTY      — site URL, default "sc-domain:heygaia.io"
 *
 * Usage:
 *   node scripts/seo/pull-gsc.mjs --dry-run   # 20 SAMPLE rows, no creds (CI-safe)
 *   node scripts/seo/pull-gsc.mjs             # real pull (needs env above)
 *   node scripts/seo/pull-gsc.mjs --days 28 --out public/data/seo/queries.json
 *
 * Deps: `googleapis` is dynamically imported ONLY for the real pull, so
 * --dry-run works with zero installs. For real pulls: pnpm add -D googleapis
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const args = new Set(process.argv.slice(2));

function flagValue(name, fallback) {
  const prefix = `${name}=`;
  for (const a of process.argv.slice(2)) {
    if (a.startsWith(prefix)) return a.slice(prefix.length);
  }
  return fallback;
}

const DRY_RUN = args.has("--dry-run");
const DAYS = Number.parseInt(flagValue("--days", "28"), 10) || 28;
const OUT = flagValue("--out", join(root, "public/data/seo/queries.json"));
const PROPERTY = process.env.GSC_PROPERTY || "sc-domain:heygaia.io";

function isoDaysAgo(n) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

// 20 deterministic SAMPLE rows — clearly labelled, never real ranking data.
// Mix: some hit existing pages (coverage check), some are striking-distance
// gaps (one+ per template), two are head terms out of range (pos < 5).
const SAMPLE_ROWS = [
  { query: "gaia vs motion", clicks: 42, impressions: 1800, ctr: 0.0233, position: 8.2 },
  { query: "sunsama alternative", clicks: 18, impressions: 1100, ctr: 0.0164, position: 12.9 },
  { query: "open source ai assistant", clicks: 88, impressions: 5400, ctr: 0.0163, position: 6.1 },
  { query: "inbox zero ai tool", clicks: 22, impressions: 1300, ctr: 0.0169, position: 10.2 },
  { query: "what is agentic ai", clicks: 15, impressions: 2100, ctr: 0.0071, position: 22.5 },
  { query: "ai meeting assistant open source", clicks: 11, impressions: 760, ctr: 0.0145, position: 16.6 },
  { query: "gaia vs routine", clicks: 21, impressions: 880, ctr: 0.0239, position: 11.5 },
  { query: "todoist vs timehero", clicks: 6, impressions: 390, ctr: 0.0154, position: 16.2 },
  { query: "timehero alternative", clicks: 9, impressions: 640, ctr: 0.0141, position: 14.8 },
  { query: "routine alternative ai", clicks: 4, impressions: 310, ctr: 0.0129, position: 19.4 },
  { query: "connect superhuman to gmail automatically", clicks: 5, impressions: 450, ctr: 0.0111, position: 22.6 },
  { query: "sync stripe with google drive automatically", clicks: 4, impressions: 380, ctr: 0.0105, position: 21.4 },
  { query: "what is timeboxing", clicks: 17, impressions: 1900, ctr: 0.0089, position: 20.3 },
  { query: "vibe coding setup guide", clicks: 7, impressions: 720, ctr: 0.0097, position: 23.7 },
  { query: "ai calendar management tool", clicks: 12, impressions: 900, ctr: 0.0133, position: 14.7 },
  { query: "superhuman alternative ai email", clicks: 14, impressions: 890, ctr: 0.0157, position: 9.1 },
  { query: "notion calendar sync todoist automation", clicks: 3, impressions: 310, ctr: 0.0097, position: 24.1 },
  { query: "ai chief of staff app", clicks: 25, impressions: 1200, ctr: 0.0208, position: 11.3 },
  { query: "heygaia pricing", clicks: 65, impressions: 900, ctr: 0.0722, position: 2.1 },
  { query: "gaia ai assistant download", clicks: 54, impressions: 700, ctr: 0.0771, position: 3.4 },
];

if (DRY_RUN) {
  const endDate = isoDaysAgo(2); // GSC data lags ~2 days
  const startDate = isoDaysAgo(2 + DAYS);
  const payload = {
    meta: {
      sample: true,
      note: "SAMPLE DATA — generated with --dry-run, not real GSC numbers.",
      property: PROPERTY,
      startDate,
      endDate,
      generatedAt: new Date().toISOString(),
    },
    rows: SAMPLE_ROWS,
  };
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(payload, null, 2)}\n`);
  console.log(`[pull-gsc] --dry-run: wrote ${payload.rows.length} SAMPLE rows -> ${OUT}`);
  process.exit(0);
}

// ---- real pull ----
const clientEmail = process.env.GSC_CLIENT_EMAIL;
let privateKey = process.env.GSC_PRIVATE_KEY;
if (!clientEmail || !privateKey) {
  console.error(
    "[pull-gsc] missing creds: set GSC_CLIENT_EMAIL and GSC_PRIVATE_KEY (see .env.example).\n" +
      "  Tip: run with --dry-run for SAMPLE output without creds.",
  );
  process.exit(1);
}
privateKey = privateKey.replace(/\\n/g, "\n");

let google;
try {
  ({ google } = await import("googleapis"));
} catch {
  console.error("[pull-gsc] `googleapis` is not installed. Run: pnpm add -D googleapis");
  process.exit(1);
}

const endDate = isoDaysAgo(2);
const startDate = isoDaysAgo(2 + DAYS);

const auth = new google.auth.JWT({
  email: clientEmail,
  key: privateKey,
  scopes: ["https://www.googleapis.com/auth/webmasters.readonly"],
});
const searchconsole = google.searchconsole({ version: "v1", auth });

console.log(`[pull-gsc] pulling query dimensions ${startDate}..${endDate} for ${PROPERTY} ...`);
const res = await searchconsole.searchanalytics.query({
  siteUrl: PROPERTY,
  requestBody: {
    startDate,
    endDate,
    dimensions: ["query"],
    rowLimit: 1000,
    dataState: "final",
  },
});

const apiRows = res.data.rows ?? [];
const rows = apiRows.map((r) => ({
  query: r.keys?.[0] ?? "",
  clicks: r.clicks ?? 0,
  impressions: r.impressions ?? 0,
  ctr: r.ctr ?? 0,
  position: r.position ?? 0,
})).filter((r) => r.query);

const payload = {
  meta: {
    sample: false,
    property: PROPERTY,
    startDate,
    endDate,
    generatedAt: new Date().toISOString(),
  },
  rows,
};
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`[pull-gsc] wrote ${rows.length} queries -> ${OUT}`);
