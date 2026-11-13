#!/usr/bin/env node
/**
 * Diffs the two builds, after masking what is noise.
 *
 *   node review/compare.mjs [--out DIR] [--threshold 0.1]
 *
 * Noise: any pixel that differs between run1 and run2 of the SAME build. Those
 * pixels (dilated by NOISE_PAD) are masked out of the before/after diff, so a
 * reported change is one that reproduced on both runs of each build.
 *
 * Output: <out>/report/data.json and <out>/report/diff/<viewport>/<file>.png
 * (the after shot dimmed, changed pixels red, masked noise blue).
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { DEFAULT_OUT } from "./config.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const req = createRequire(join(HERE, "..", "package.json"));
const { PNG } = req("pngjs");
const pixelmatch = (await import(req.resolve("pixelmatch"))).default;

const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const OUT = resolve(arg("out", DEFAULT_OUT));
const THRESHOLD = Number(arg("threshold", 0.1));
const NOISE_PAD = 3;
const CELL = 8;
const MERGE_GAP = 24;
const MAX_REGIONS = 40;

const shotsDir = (label, run) => join(OUT, "shots", label, `run${run}`);
const manifest = (label, run) => {
  const p = join(shotsDir(label, run), "manifest.json");
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf8"));
};
const index = (m) => new Map((m?.shots ?? []).map((s) => [`${s.key}|${s.vp}|${s.state}`, s]));

const runs = {
  before: [manifest("before", 1), manifest("before", 2)],
  after: [manifest("after", 1), manifest("after", 2)],
};
if (!runs.before[0]) throw new Error("no before run1 manifest: capture.mjs --label before --run 1");
const idx = { before: runs.before.map(index), after: runs.after.map(index) };
const inventory = JSON.parse(readFileSync(join(OUT, "inventory.json"), "utf8"));
const targetByKey = new Map(inventory.targets.map((t) => [t.key, t]));
/** Routes the v3 PR deletes on purpose, with who approved it (review/approved-removals.json). */
const APPROVED_REMOVALS = JSON.parse(readFileSync(join(HERE, "approved-removals.json"), "utf8"));

const read = (label, run, rel) => PNG.sync.read(readFileSync(join(shotsDir(label, run), rel)));

function pad(img, w, h) {
  if (img.width === w && img.height === h) return img;
  const out = new PNG({ width: w, height: h });
  out.data.fill(0);
  PNG.bitblt(img, out, 0, 0, Math.min(img.width, w), Math.min(img.height, h), 0, 0);
  return out;
}

/** Changed-pixel mask between two shots (1 = differs); size mismatches count the overhang as changed. */
function changedMask(a, b) {
  const w = Math.max(a.width, b.width);
  const h = Math.max(a.height, b.height);
  const pa = pad(a, w, h);
  const pb = pad(b, w, h);
  const out = new PNG({ width: w, height: h });
  pixelmatch(pa.data, pb.data, out.data, w, h, { threshold: THRESHOLD, includeAA: false, diffColor: [255, 0, 0], aaColor: [255, 255, 0], diffMask: true });
  const mask = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) if (out.data[i * 4] === 255 && out.data[i * 4 + 1] === 0 && out.data[i * 4 + 3] !== 0) mask[i] = 1;
  return { mask, w, h, a: pa, b: pb };
}

function dilate(mask, w, h, r) {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      if (!mask[y * w + x]) continue;
      for (let dy = -r; dy <= r; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= h) continue;
        const row = yy * w;
        for (let dx = -r; dx <= r; dx++) {
          const xx = x + dx;
          if (xx >= 0 && xx < w) out[row + xx] = 1;
        }
      }
    }
  return out;
}

/** Noise mask of one build at this shot: pixels its two runs disagree on. Null when run2 is absent. */
function noiseOf(label, key) {
  const r1 = idx[label][0]?.get(key);
  const r2 = idx[label][1]?.get(key);
  if (!r1?.file || !r2?.file) return null;
  const { mask, w, h } = changedMask(read(label, 1, r1.file), read(label, 2, r2.file));
  let n = 0;
  for (const v of mask) n += v;
  return { mask: n ? dilate(mask, w, h, NOISE_PAD) : mask, w, h, px: n };
}

/** Cluster changed pixels into boxes on a CELL grid, merging boxes within MERGE_GAP. */
function regions(mask, w, h) {
  const gw = Math.ceil(w / CELL);
  const gh = Math.ceil(h / CELL);
  const grid = new Uint8Array(gw * gh);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (mask[y * w + x]) grid[((y / CELL) | 0) * gw + ((x / CELL) | 0)] = 1;
  const seen = new Uint8Array(gw * gh);
  const boxes = [];
  for (let i = 0; i < grid.length; i++) {
    if (!grid[i] || seen[i]) continue;
    const stack = [i];
    seen[i] = 1;
    let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
    while (stack.length) {
      const j = stack.pop();
      const gx = j % gw, gy = (j / gw) | 0;
      x0 = Math.min(x0, gx); y0 = Math.min(y0, gy); x1 = Math.max(x1, gx); y1 = Math.max(y1, gy);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = gx + dx, ny = gy + dy;
        if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
        const k = ny * gw + nx;
        if (grid[k] && !seen[k]) { seen[k] = 1; stack.push(k); }
      }
    }
    boxes.push({ x: x0 * CELL, y: y0 * CELL, w: (x1 - x0 + 1) * CELL, h: (y1 - y0 + 1) * CELL });
  }
  let merged = true;
  while (merged) {
    merged = false;
    for (let i = 0; i < boxes.length && !merged; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (a.x - MERGE_GAP < b.x + b.w && b.x - MERGE_GAP < a.x + a.w && a.y - MERGE_GAP < b.y + b.h && b.y - MERGE_GAP < a.y + a.h) {
          const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
          boxes[i] = { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
          boxes.splice(j, 1);
          merged = true;
          break;
        }
      }
  }
  return boxes
    .map((b) => ({ ...b, w: Math.min(b.w, w - b.x), h: Math.min(b.h, h - b.y) }))
    .sort((p, q) => q.w * q.h - p.w * p.h)
    .slice(0, MAX_REGIONS);
}

function diffImage(after, mask, noise, w, h) {
  const out = new PNG({ width: w, height: h });
  for (let i = 0; i < w * h; i++) {
    const o = i * 4;
    if (mask[i]) out.data.set([255, 40, 40, 255], o);
    else if (noise?.[i]) out.data.set([60, 110, 255, 255], o);
    else {
      const g = (0.3 * after.data[o] + 0.59 * after.data[o + 1] + 0.11 * after.data[o + 2]) * 0.35;
      out.data.set([g, g, g, 255], o);
    }
  }
  return out;
}

const AREAS = arg("areas")?.split(",");
const NAME = arg("name");
if (AREAS && !NAME) throw new Error("--areas needs --name (the report/areas/<name>.json it writes)");
const areaOfShot = (k) => targetByKey.get(k.split("|")[0])?.area;
const keys = [...new Set([...idx.before[0].keys(), ...(idx.after[0]?.keys() ?? [])])]
  .filter((k) => !AREAS || AREAS.includes(areaOfShot(k)))
  .sort();
const rows = [];
const noiseStats = { before: { shots: 0, stable: 0, px: 0, total: 0 }, after: { shots: 0, stable: 0, px: 0, total: 0 } };
let n = 0;
for (const key of keys) {
  const b = idx.before[0].get(key);
  const a = idx.after[0]?.get(key);
  const t = targetByKey.get(b?.key ?? a?.key);
  const row = {
    key: b?.key ?? a?.key,
    vp: b?.vp ?? a?.vp,
    state: b?.state ?? a?.state,
    kind: b?.kind ?? a?.kind,
    stateLabel: b?.stateLabel ?? a?.stateLabel,
    area: t?.area,
    label: t?.label,
    file: t?.file,
    before: b?.file ? `shots/before/run1/${b.file}` : null,
    after: a?.file ? `shots/after/run1/${a.file}` : null,
    beforeIssue: b?.error ?? (b?.missing ? "trigger not found" : b?.hidden ? "trigger hidden at this viewport" : null),
    afterIssue: a ? (a.error ?? (a.missing ? "trigger not found" : a.hidden ? "trigger hidden at this viewport" : null)) : runs.after[0] ? "not captured" : null,
  };
  const removal = APPROVED_REMOVALS[row.key];
  if (removal) {
    // An approved removal is not a diff: record why, and do not compare.
    rows.push({ ...row, removed: removal, afterIssue: null });
    continue;
  }
  const noise = {};
  for (const label of ["before", "after"]) {
    const nz = runs[label][1] ? noiseOf(label, key) : null;
    if (nz) {
      noiseStats[label].shots++;
      noiseStats[label].px += nz.px;
      noiseStats[label].total += nz.w * nz.h;
      if (nz.px === 0) noiseStats[label].stable++;
      row[`${label}NoisePct`] = (100 * nz.px) / (nz.w * nz.h);
    }
    noise[label] = nz;
  }
  if (row.before && row.after) {
    const { mask, w, h, b: afterImg } = changedMask(read("before", 1, b.file), read("after", 1, a.file));
    const masked = new Uint8Array(w * h);
    for (const nz of [noise.before, noise.after]) if (nz) for (let y = 0; y < Math.min(h, nz.h); y++) for (let x = 0; x < Math.min(w, nz.w); x++) if (nz.mask[y * nz.w + x]) masked[y * w + x] = 1;
    let changed = 0;
    for (let i = 0; i < w * h; i++) if (mask[i] && masked[i]) mask[i] = 0;
    for (const v of mask) changed += v;
    row.w = w;
    row.h = h;
    row.changedPct = (100 * changed) / (w * h);
    row.regions = changed ? regions(mask, w, h) : [];
    const rel = `report/diff/${a.file}`;
    mkdirSync(join(OUT, dirname(rel)), { recursive: true });
    writeFileSync(join(OUT, rel), PNG.sync.write(diffImage(afterImg, mask, masked, w, h)));
    row.diff = rel;
  }
  rows.push(row);
  if (++n % 50 === 0) process.stdout.write(`\r  compared ${n}/${keys.length}`);
}

const pct = (s) => (s.total ? (100 * s.px) / s.total : null);
const data = {
  generatedAt: new Date().toISOString(),
  before: runs.before[0] && { base: runs.before[0].base, capturedAt: runs.before[0].capturedAt, runs: runs.before.filter(Boolean).length },
  after: runs.after[0] && { base: runs.after[0].base, capturedAt: runs.after[0].capturedAt, runs: runs.after.filter(Boolean).length },
  noise: Object.fromEntries(Object.entries(noiseStats).map(([k, s]) => [k, { shots: s.shots, stableShots: s.stable, noisyPixelPct: pct(s) }])),
  skipped: inventory.skipped,
  blockedMutations: { before: runs.before[0]?.blockedMutations ?? [], after: runs.after[0]?.blockedMutations ?? [] },
  rows,
};
// A per-area run (--areas/--name) publishes only that area's rows, for work to start before the rest finishes.
const outFile = AREAS ? join(OUT, "report", "areas", `${NAME}.json`) : join(OUT, "report", "data.json");
mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(outFile, JSON.stringify(AREAS ? { ...data, areas: AREAS, rows: [...rows].sort((p, q) => (q.changedPct ?? -1) - (p.changedPct ?? -1)) } : data, null, AREAS ? 1 : 0));
console.log(`\n  ${rows.length} shots compared -> ${outFile}`);
for (const [k, s] of Object.entries(data.noise)) if (s.shots) console.log(`  noise ${k}: ${s.stableShots}/${s.shots} shots pixel-identical across runs, ${s.noisyPixelPct.toFixed(4)}% of pixels masked`);
