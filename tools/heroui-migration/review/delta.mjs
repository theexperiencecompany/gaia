#!/usr/bin/env node
/**
 * Which shots got worse between two v3 builds, each already diffed against the same v2 reference.
 *
 *   node review/delta.mjs <older.json> <newer.json> [--min 0.5]
 *
 * Inputs are report/data.json or report/areas/<name>.json files. A shot is worse when its changed share
 * of pixels rose by more than --min percentage points, or when it renders/triggers on the older build
 * and not on the newer one. Prints JSON grouped by area.
 */
import { readFileSync } from "node:fs";

const [olderPath, newerPath] = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const minIdx = process.argv.indexOf("--min");
const MIN = minIdx === -1 ? 0.5 : Number(process.argv[minIdx + 1]);
if (!olderPath || !newerPath) throw new Error("usage: delta.mjs <older.json> <newer.json> [--min 0.5]");

const rowsOf = (p) => new Map(JSON.parse(readFileSync(p, "utf8")).rows.map((r) => [`${r.key}|${r.vp}|${r.state}`, r]));
const older = rowsOf(olderPath);
const newer = rowsOf(newerPath);

const worse = {};
for (const [id, n] of newer) {
  const o = older.get(id);
  // A shot the older build could not take has no baseline to be worse than.
  if (!o || n.removed || o.afterIssue) continue;
  const lostRender = !o.afterIssue && n.afterIssue;
  const rise = (n.changedPct ?? 0) - (o.changedPct ?? 0);
  if (!lostRender && !(rise > MIN)) continue;
  (worse[n.area] ??= []).push({
    route: n.key,
    viewport: n.vp,
    state: n.stateLabel,
    olderPct: o.changedPct ?? null,
    newerPct: n.changedPct ?? null,
    newerIssue: n.afterIssue ?? null,
    newerAfter: n.after,
    newerDiff: n.diff ?? null,
  });
}
for (const list of Object.values(worse)) list.sort((p, q) => (q.newerPct ?? 100) - (q.olderPct ?? 0) - ((p.newerPct ?? 100) - (p.olderPct ?? 0)));
console.log(JSON.stringify(worse, null, 1));
