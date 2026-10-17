// Bake the vector logo into the terminal header's pixel tables (src/ui/header/logo-cells.generated.ts).
// Deterministic: searches scale + sub-pixel offset against an N x N grid (2 pixels per terminal row),
// scores each fit, applies minimal cleanup, and picks the xterm-256 colours for the three fills.
// Usage: node scripts/bake-logo.mjs [output path]
import { writeFileSync } from "node:fs";
import { FILLS, hexRgb, renderClasses, VB_H, VB_W } from "./logo-vector.mjs";

const DEFAULT_OUTPUT = new URL("../src/ui/header/logo-cells.generated.ts", import.meta.url);

// Header size -> the line count its bake targets; cropping to ink trims one line off each.
const SIZES = { large: 12, small: 10 };

const SS = 16; // supersamples per target pixel per axis
const OFFSET_STEP = 1; // in supersamples -> 1/16 px offsets
const SCALE_STEP = 0.125; // logo width search step, in target px
const K = FILLS.length;

/** Render the logo L px wide at SS supersampling inside an (N+2) px canvas, logo origin at (1,1) px. */
function supersampled(N, L) {
  const unitsPerPx = VB_W / L;
  const canvasPx = N + 2;
  const window = [-unitsPerPx, -unitsPerPx, canvasPx * unitsPerPx, canvasPx * unitsPerPx];
  const side = canvasPx * SS;
  return { side, cls: renderClasses(window, side, side) };
}

/** Prefix sums per fill so any block coverage is O(1). */
function prefix({ side, cls }) {
  const P = Array.from({ length: K }, () => new Int32Array((side + 1) * (side + 1)));
  for (let y = 0; y < side; y++)
    for (let x = 0; x < side; x++) {
      const c = cls[y * side + x];
      for (let k = 0; k < K; k++) {
        const i = (y + 1) * (side + 1) + (x + 1);
        P[k][i] = P[k][i - 1] + P[k][i - (side + 1)] - P[k][i - (side + 1) - 1] + (c === k ? 1 : 0);
      }
    }
  return P;
}

function blockSum(Pk, side, x0, y0, x1, y1) {
  const w = side + 1;
  return Pk[y1 * w + x1] - Pk[y0 * w + x1] - Pk[y1 * w + x0] + Pk[y0 * w + x0];
}

/** Per-pixel fill coverage of an N x N grid whose origin sits (ox, oy) supersamples into the canvas. */
function coverage(P, side, N, ox, oy) {
  const cov = [];
  let inside = 0;
  for (let gy = 0; gy < N; gy++)
    for (let gx = 0; gx < N; gx++) {
      const x0 = ox + gx * SS;
      const y0 = oy + gy * SS;
      const c = P.map((Pk) => blockSum(Pk, side, x0, y0, x0 + SS, y0 + SS) / (SS * SS));
      cov.push(c);
      inside += c.reduce((a, b) => a + b, 0);
    }
  return { cov, inside };
}

// Coverage a pixel needs to count as ink; above 0.5 opens thin gaps, below closes them.
const INK_THRESHOLDS = [0.4, 0.5, 0.6];

function assign(cov, threshold) {
  return cov.map((c) => {
    const total = c.reduce((a, b) => a + b, 0);
    if (total < threshold) return -1;
    let best = 0;
    for (let k = 1; k < K; k++) if (c[k] > c[best]) best = k;
    return best;
  });
}

const DIRS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];

function neighbours(g, N, i) {
  const x = i % N;
  const y = Math.floor(i / N);
  return DIRS.map(([dx, dy]) => {
    const nx = x + dx;
    const ny = y + dy;
    return nx < 0 || ny < 0 || nx >= N || ny >= N ? -1 : g[ny * N + nx];
  });
}

const isInk = (c) => c >= 0;

/** Connected regions of pixels matching pred; with sameFill, a region is also one fill. */
function components(g, N, pred, sameFill) {
  const seen = new Uint8Array(N * N);
  let count = 0;
  for (let i = 0; i < N * N; i++) {
    if (seen[i] || !pred(g[i])) continue;
    count++;
    const stack = [i];
    seen[i] = 1;
    while (stack.length) {
      const j = stack.pop();
      const x = j % N;
      const y = Math.floor(j / N);
      for (const [dx, dy] of DIRS) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= N || ny >= N) continue;
        const n = ny * N + nx;
        if (!seen[n] && pred(g[n]) && (!sameFill || g[n] === g[j])) {
          seen[n] = 1;
          stack.push(n);
        }
      }
    }
  }
  return count;
}

/** Counts of the pixel-art defects the score penalises. */
function defects(g, N, centre) {
  let isolated = 0;
  let stray = 0;
  let holes = 0;
  let notches = 0;
  let spurs = 0;
  for (let i = 0; i < N * N; i++) {
    const inkNb = neighbours(g, N, i).filter(isInk);
    if (g[i] >= 0) {
      if (inkNb.length === 0) isolated++;
      else if (inkNb.length === 1) spurs++;
      else if (inkNb.every((c) => c !== g[i])) stray++;
    } else if (inkNb.length === 4) holes++;
    else if (inkNb.length === 3) notches++;
  }
  // 3-fold symmetry: rotate each ink pixel centre by 120 and 240 degrees about the logo centre.
  let symMiss = 0;
  for (let i = 0; i < N * N; i++) {
    if (g[i] < 0) continue;
    for (const deg of [120, 240]) {
      const a = (deg * Math.PI) / 180;
      const x = (i % N) + 0.5 - centre[0];
      const y = Math.floor(i / N) + 0.5 - centre[1];
      const rx = Math.floor(centre[0] + x * Math.cos(a) - y * Math.sin(a));
      const ry = Math.floor(centre[1] + x * Math.sin(a) + y * Math.cos(a));
      const r = rx < 0 || ry < 0 || rx >= N || ry >= N ? -1 : g[ry * N + rx];
      if (r !== g[i]) symMiss++;
    }
  }
  const inkComponents = components(g, N, isInk, false);
  const fillComponents = FILLS.map((_, k) => components(g, N, (c) => c === k, true));
  return { isolated, stray, holes, notches, spurs, symMiss, inkComponents, fillComponents };
}

// The vector itself: 3 lobes, each fill appears as 3 separate regions (measured at high resolution).
const VECTOR_INK_COMPONENTS = 3;
const VECTOR_FILL_COMPONENTS = [3, 3, 3];

// Cost per target pixel the logo is drawn smaller than its rows allow.
const SHRINK_COST = 4;

function score(cov, inkTotal, insideInk, g, d, shrink) {
  let err = inkTotal - insideInk; // ink cropped off the grid
  cov.forEach((c, i) => {
    const total = c.reduce((a, b) => a + b, 0);
    err += g[i] < 0 ? total : 1 - c[g[i]];
  });
  const topology =
    Math.abs(d.inkComponents - VECTOR_INK_COMPONENTS) +
    d.fillComponents.reduce((s, n, k) => s + Math.abs(n - VECTOR_FILL_COMPONENTS[k]), 0);
  // A closed or extra gap is not a trade-off, it is a different logo.
  if (topology > 0) return Number.POSITIVE_INFINITY;
  // Error as % of the logo's ink, so a smaller fit does not win just by having less ink.
  const fidelity = (100 * err) / inkTotal;
  return (
    fidelity +
    4 * d.isolated +
    3 * d.stray +
    4 * d.holes +
    2 * d.spurs +
    0.5 * d.notches +
    0.5 * d.symMiss +
    SHRINK_COST * shrink
  );
}

/** Minimal cleanup: drop isolated pixels, fill 1-px holes, recolour single-pixel colour strays. */
function cleanup(g, N) {
  const out = g.slice();
  const majority = (cs) => {
    const counts = new Map();
    for (const c of cs) if (c >= 0) counts.set(c, (counts.get(c) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
  };
  for (let i = 0; i < N * N; i++) {
    const inkNb = neighbours(g, N, i).filter(isInk);
    if (g[i] >= 0 && inkNb.length === 0) out[i] = -1;
    else if (g[i] < 0 && inkNb.length === 4) out[i] = majority(inkNb);
    else if (g[i] >= 0 && inkNb.length > 0 && inkNb.every((c) => c !== g[i])) out[i] = majority(inkNb);
  }
  return out;
}

/** The best-scoring cleaned N x N grid of fill classes. */
function bake(N) {
  let best = null;
  // The mark must fill its rows: logo height between N-3 and N px, width following the vector's aspect.
  const minL = ((N - 3) * VB_W) / VB_H;
  const maxL = (N * VB_W) / VB_H;
  for (let L = Math.ceil(minL / SCALE_STEP) * SCALE_STEP; L <= maxL + 1e-9; L += SCALE_STEP) {
    const ss = supersampled(N, L);
    const P = prefix(ss);
    const inkTotal = P.reduce((s, Pk) => s + Pk[Pk.length - 1], 0) / (SS * SS);
    const H = (L * VB_H) / VB_W;
    // The logo spans [SS, SS + L*SS) in the canvas; grid origins keep it (nearly) inside.
    for (let oy = 0; oy <= Math.round((2 + N - H) * SS) && oy + N * SS <= ss.side; oy += OFFSET_STEP)
      for (let ox = 0; ox <= Math.round((2 + N - L) * SS) && ox + N * SS <= ss.side; ox += OFFSET_STEP) {
        const { cov, inside } = coverage(P, ss.side, N, ox, oy);
        const centre = [1 + L / 2 - ox / SS, 1 + H / 2 - oy / SS];
        for (const threshold of INK_THRESHOLDS) {
          const g = assign(cov, threshold);
          const s = score(cov, inkTotal, inside, g, defects(g, N, centre), maxL - L);
          if (!best || s < best.score - 1e-9) best = { score: s, g };
        }
      }
  }
  if (!Number.isFinite(best.score)) {
    throw new Error(`no fit at ${N / 2} lines keeps the 3 gaps and 9 fill regions`);
  }
  return cleanup(best.g, N);
}

/** Rows of fill letters ("." empty), trimmed to the ink and padded to whole text lines. */
function pixelRows(g, N) {
  const rows = Array.from({ length: N }, (_, y) =>
    Array.from({ length: N }, (_, x) => (g[y * N + x] < 0 ? "." : FILLS[g[y * N + x]].key)),
  );
  const inkRows = rows.flatMap((r, y) => (r.some((c) => c !== ".") ? [y] : []));
  const inkCols = rows[0].flatMap((_, x) => (rows.some((r) => r[x] !== ".") ? [x] : []));
  const out = rows
    .slice(inkRows[0], inkRows.at(-1) + 1)
    .map((r) => r.slice(inkCols[0], inkCols.at(-1) + 1).join(""));
  if (out.length % 2) out.push(".".repeat(out[0].length));
  return out;
}

// xterm-256: indices 0-15 are re-themed by every terminal, so only the 6x6x6 cube and grey ramp count.
const CUBE_LEVELS = [0, 95, 135, 175, 215, 255];
const FIRST_FIXED_INDEX = 16;
const GREY_RAMP_START = 232;

function xterm(i) {
  if (i >= GREY_RAMP_START) {
    const v = 8 + (i - GREY_RAMP_START) * 10;
    return [v, v, v];
  }
  const n = i - FIRST_FIXED_INDEX;
  return [CUBE_LEVELS[Math.floor(n / 36)], CUBE_LEVELS[Math.floor(n / 6) % 6], CUBE_LEVELS[n % 6]];
}

function oklab([r, g, b]) {
  const lin = (c) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const [R, G, B] = [lin(r), lin(g), lin(b)];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

// The picks must stay this fraction of each true pair's distance apart, or two lobes merge.
const MIN_SEPARATION = 0.6;
const CANDIDATES_PER_FILL = 12;

/** The xterm-256 indices nearest the fills in OKLab that still keep the three apart. */
function ansi256Palette() {
  const targets = FILLS.map((f) => oklab(hexRgb(f.hex)));
  const candidates = targets.map((t) => {
    const ranked = [];
    for (let i = FIRST_FIXED_INDEX; i < 256; i++) {
      const lab = oklab(xterm(i));
      ranked.push({ i, lab, d: dist(t, lab) });
    }
    return ranked.sort((a, b) => a.d - b.d || a.i - b.i).slice(0, CANDIDATES_PER_FILL);
  });
  let best = null;
  for (const a of candidates[0])
    for (const b of candidates[1])
      for (const c of candidates[2]) {
        const picks = [a, b, c];
        const apart = picks.every((p, x) =>
          picks.every(
            (q, y) => y <= x || dist(p.lab, q.lab) >= MIN_SEPARATION * dist(targets[x], targets[y]),
          ),
        );
        const cost = a.d + b.d + c.d;
        if (apart && (!best || cost < best.cost)) best = { cost, picks };
      }
  return Object.fromEntries(FILLS.map((f, k) => [f.key, best.picks[k].i]));
}

function moduleSource() {
  const sizes = Object.entries(SIZES).map(([size, lines]) => {
    const N = lines * 2;
    const rows = pixelRows(bake(N), N).map((r) => `    "${r}",`);
    return [`  ${size}: [`, ...rows, "  ],"].join("\n");
  });
  const truecolor = FILLS.map((f) => `${f.key}: "${f.hex}"`).join(", ");
  const ansi256 = Object.entries(ansi256Palette())
    .map(([key, i]) => `${key}: ${i}`)
    .join(", ");
  return `// Generated by packages/cli/scripts/bake-logo.mjs from apps/web/public/brand/gaia_logo.svg.
// Do not edit: run \`pnpm --filter @heygaia/cli bake:logo\`.

/** Logo pixels, two per terminal line: d dark, m mid, l light fill, . empty. */
export const LOGO_PIXELS = {
${sizes.join("\n")}
} as const;

/** The SVG's own fills. */
export const LOGO_TRUECOLOR = { ${truecolor} } as const;

/** The nearest xterm-256 colours (16-255) to the fills that keep the three apart. */
export const LOGO_ANSI256 = { ${ansi256} } as const;
`;
}

writeFileSync(process.argv[2] ?? DEFAULT_OUTPUT, moduleSource());
