// Bake the vector logo into the terminal header's pixel tables (src/ui/header/logo-cells.generated.ts).
// Deterministic: searches scale + sub-pixel offset against a W x H grid (2 pixels per terminal row),
// scores each fit, applies minimal cleanup, and picks the xterm-256 colours for the three fills.
// Also bakes the small logo as ANSI lines into install.sh, between its markers.
// Usage: node scripts/bake-logo.mjs [table output path] [install.sh path]
import { readFileSync, writeFileSync } from "node:fs";
import { FILLS, hexRgb, renderClasses, VB_H, VB_W } from "./logo-vector.mjs";

const DEFAULT_OUTPUT = new URL("../src/ui/header/logo-cells.generated.ts", import.meta.url);
const DEFAULT_INSTALLER = new URL("../install.sh", import.meta.url);

// The markers around the lines baked into install.sh.
const BEGIN_MARKER = "# BEGIN GENERATED LOGO (packages/cli/scripts/bake-logo.mjs; do not edit)";
const END_MARKER = "# END GENERATED LOGO";

// The line count the bake targets; cropping to ink trims it to 11. Smaller fits read as blobs.
// The one size every header draws: the installer, `gaia up` and --version.
const LOGO_LINES = 12;

// A pixel's height over its width: a half block is square at line height 1.0. Baking onto taller
// pixels for wider-spaced terminals cost the mark its gaps at this size, so it reads as a blob.
const PIXEL_ASPECT = 1.0;

const SS = 16; // supersamples per target pixel per axis
const OFFSET_STEP = 1; // in supersamples -> 1/16 px offsets
const SCALE_STEP = 0.125; // logo width search step, in target px
const K = FILLS.length;

/** Render the logo L px wide at SS supersampling on a (W+2) x (H+2) px canvas, logo origin at (1,1) px. */
function supersampled({ W, H }, L) {
  const unitsPerPx = VB_W / L;
  const unitsPerRow = unitsPerPx * PIXEL_ASPECT;
  const window = [-unitsPerPx, -unitsPerRow, (W + 2) * unitsPerPx, (H + 2) * unitsPerRow];
  const width = (W + 2) * SS;
  const height = (H + 2) * SS;
  return { width, height, cls: renderClasses(window, width, height) };
}

/** Prefix sums per fill so any block coverage is O(1). */
function prefix({ width, height, cls }) {
  const stride = width + 1;
  const P = Array.from({ length: K }, () => new Int32Array(stride * (height + 1)));
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const c = cls[y * width + x];
      for (let k = 0; k < K; k++) {
        const i = (y + 1) * stride + (x + 1);
        P[k][i] = P[k][i - 1] + P[k][i - stride] - P[k][i - stride - 1] + (c === k ? 1 : 0);
      }
    }
  return P;
}

function blockSum(Pk, stride, x0, y0, x1, y1) {
  return Pk[y1 * stride + x1] - Pk[y0 * stride + x1] - Pk[y1 * stride + x0] + Pk[y0 * stride + x0];
}

/** Per-pixel fill coverage of a W x H grid whose origin sits (ox, oy) supersamples into the canvas. */
function coverage(P, stride, { W, H }, ox, oy) {
  const cov = [];
  let inside = 0;
  for (let gy = 0; gy < H; gy++)
    for (let gx = 0; gx < W; gx++) {
      const x0 = ox + gx * SS;
      const y0 = oy + gy * SS;
      const c = P.map((Pk) => blockSum(Pk, stride, x0, y0, x0 + SS, y0 + SS) / (SS * SS));
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

function neighbours(g, { W, H }, i) {
  const x = i % W;
  const y = Math.floor(i / W);
  return DIRS.map(([dx, dy]) => {
    const nx = x + dx;
    const ny = y + dy;
    return nx < 0 || ny < 0 || nx >= W || ny >= H ? -1 : g[ny * W + nx];
  });
}

const isInk = (c) => c >= 0;

/** Connected regions of pixels matching pred; with sameFill, a region is also one fill. */
function components(g, { W, H }, pred, sameFill) {
  const seen = new Uint8Array(W * H);
  let count = 0;
  for (let i = 0; i < W * H; i++) {
    if (seen[i] || !pred(g[i])) continue;
    count++;
    const stack = [i];
    seen[i] = 1;
    while (stack.length) {
      const j = stack.pop();
      const x = j % W;
      const y = Math.floor(j / W);
      for (const [dx, dy] of DIRS) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
        const n = ny * W + nx;
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
function defects(g, grid, centre) {
  const { W, H } = grid;
  let isolated = 0;
  let stray = 0;
  let holes = 0;
  let notches = 0;
  let spurs = 0;
  for (let i = 0; i < W * H; i++) {
    const inkNb = neighbours(g, grid, i).filter(isInk);
    if (g[i] >= 0) {
      if (inkNb.length === 0) isolated++;
      else if (inkNb.length === 1) spurs++;
      else if (inkNb.every((c) => c !== g[i])) stray++;
    } else if (inkNb.length === 4) holes++;
    else if (inkNb.length === 3) notches++;
  }
  // 3-fold symmetry: rotate each ink pixel centre by 120 and 240 degrees about the logo centre,
  // measured as drawn, where a row is PIXEL_ASPECT columns tall.
  let symMiss = 0;
  for (let i = 0; i < W * H; i++) {
    if (g[i] < 0) continue;
    for (const deg of [120, 240]) {
      const a = (deg * Math.PI) / 180;
      const x = (i % W) + 0.5 - centre[0];
      const y = (Math.floor(i / W) + 0.5 - centre[1]) * PIXEL_ASPECT;
      const rx = Math.floor(centre[0] + x * Math.cos(a) - y * Math.sin(a));
      const ry = Math.floor(centre[1] + (x * Math.sin(a) + y * Math.cos(a)) / PIXEL_ASPECT);
      const r = rx < 0 || ry < 0 || rx >= W || ry >= H ? -1 : g[ry * W + rx];
      if (r !== g[i]) symMiss++;
    }
  }
  const inkComponents = components(g, grid, isInk, false);
  const fillComponents = FILLS.map((_, k) => components(g, grid, (c) => c === k, true));
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
function cleanup(g, grid) {
  const out = g.slice();
  const majority = (cs) => {
    const counts = new Map();
    for (const c of cs) if (c >= 0) counts.set(c, (counts.get(c) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
  };
  for (let i = 0; i < grid.W * grid.H; i++) {
    const inkNb = neighbours(g, grid, i).filter(isInk);
    if (g[i] >= 0 && inkNb.length === 0) out[i] = -1;
    else if (g[i] < 0 && inkNb.length === 4) out[i] = majority(inkNb);
    else if (g[i] >= 0 && inkNb.length > 0 && inkNb.every((c) => c !== g[i])) out[i] = majority(inkNb);
  }
  return out;
}

/** Logo width in columns when it is `rows` pixel rows tall. */
const widthAt = (rows) => (rows * PIXEL_ASPECT * VB_W) / VB_H;

/** The best-scoring cleaned grid of fill classes, H pixel rows tall and as wide as the logo can get. */
function bake(H) {
  let best = null;
  // The mark must fill its rows: logo height between H-3 and H px, width following the vector's aspect.
  const minL = widthAt(H - 3);
  const maxL = widthAt(H);
  const grid = { W: Math.ceil(maxL - 1e-9), H };
  for (let L = Math.ceil(minL / SCALE_STEP) * SCALE_STEP; L <= maxL + 1e-9; L += SCALE_STEP) {
    const ss = supersampled(grid, L);
    const P = prefix(ss);
    const inkTotal = P.reduce((s, Pk) => s + Pk[Pk.length - 1], 0) / (SS * SS);
    const logoH = (L * VB_H) / VB_W / PIXEL_ASPECT;
    // The logo spans [SS, SS + L*SS) in the canvas; grid origins keep it (nearly) inside.
    for (let oy = 0; oy <= Math.round((2 + H - logoH) * SS) && oy + H * SS <= ss.height; oy += OFFSET_STEP)
      for (let ox = 0; ox <= Math.round((2 + grid.W - L) * SS) && ox + grid.W * SS <= ss.width; ox += OFFSET_STEP) {
        const { cov, inside } = coverage(P, ss.width + 1, grid, ox, oy);
        const centre = [1 + L / 2 - ox / SS, 1 + logoH / 2 - oy / SS];
        for (const threshold of INK_THRESHOLDS) {
          const g = assign(cov, threshold);
          const s = score(cov, inkTotal, inside, g, defects(g, grid, centre), maxL - L);
          if (!best || s < best.score - 1e-9) best = { score: s, g };
        }
      }
  }
  if (!Number.isFinite(best.score)) {
    throw new Error(`no fit at ${H / 2} lines keeps the 3 gaps and 9 fill regions`);
  }
  return { grid, g: cleanup(best.g, grid) };
}

/** Rows of fill letters ("." empty), trimmed to the ink and padded to whole text lines. */
function pixelRows({ grid: { W, H }, g }) {
  const rows = Array.from({ length: H }, (_, y) =>
    Array.from({ length: W }, (_, x) => (g[y * W + x] < 0 ? "." : FILLS[g[y * W + x]].key)),
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

function moduleSource(pixels) {
  const rows = pixels.map((r) => `  "${r}",`);
  const truecolor = FILLS.map((f) => `${f.key}: "${f.hex}"`).join(", ");
  const ansi256 = Object.entries(ansi256Palette())
    .map(([key, i]) => `${key}: ${i}`)
    .join(", ");
  return `// Generated by packages/cli/scripts/bake-logo.mjs from apps/web/public/brand/gaia_logo.svg.
// Do not edit: run \`pnpm --filter @heygaia/cli bake:logo\`.

/** Logo pixels, two per terminal line: d dark, m mid, l light fill, . empty. */
export const LOGO_PIXELS = [
${rows.join("\n")}
] as const;

/** The SVG's own fills. */
export const LOGO_TRUECOLOR = { ${truecolor} } as const;

/** The nearest xterm-256 colours (16-255) to the fills that keep the three apart. */
export const LOGO_ANSI256 = { ${ansi256} } as const;
`;
}

// The same cells and escapes as src/ui/header/logo.ts (a test holds the two together), written
// as \033 so install.sh's printf, not a literal escape byte, emits them.
const ESC = "\\033[";
const SGR_RESET_FG = `${ESC}39m`;
const SGR_RESET_BG = `${ESC}49m`;

const CELL_GLYPHS = { both: "█", top: "▀", bottom: "▄", none: " " };

const SGR = {
  truecolor: (fill, ground) => {
    const [r, g, b] = hexRgb(FILLS.find((f) => f.key === fill).hex);
    return `${ESC}${ground};2;${r};${g};${b}m`;
  },
  ansi256: (fill, ground, palette) => `${ESC}${ground};5;${palette[fill]}m`,
};

/** One text line of the logo for a colour variant: a run of identical cells shares its escapes. */
function installerLine(topRow, bottomRow, variant, palette) {
  const fill = (ch) => (ch === "." || ch === undefined ? null : ch);
  const cells = [...topRow].map((ch, x) => {
    const top = fill(ch);
    const bottom = fill(bottomRow[x]);
    if (variant === "plain") {
      const glyph = top && bottom ? "both" : top ? "top" : bottom ? "bottom" : "none";
      return { ch: CELL_GLYPHS[glyph], fg: null, bg: null };
    }
    if (!top && !bottom) return { ch: " ", fg: null, bg: null };
    if (top === bottom) return { ch: " ", fg: null, bg: top };
    if (!top) return { ch: CELL_GLYPHS.bottom, fg: bottom, bg: null };
    return { ch: CELL_GLYPHS.top, fg: top, bg: bottom };
  });
  const paint = ({ fg, bg }, run) => {
    const colour = variant === "truecolor" ? SGR.truecolor : (f, g) => SGR.ansi256(f, g, palette);
    const open = (fg ? colour(fg, 38) : "") + (bg ? colour(bg, 48) : "");
    return open + run + (bg ? SGR_RESET_BG : "") + (fg ? SGR_RESET_FG : "");
  };
  let line = "";
  let run = "";
  let runCell = null;
  for (const cell of cells) {
    if (runCell && (cell.fg !== runCell.fg || cell.bg !== runCell.bg)) {
      line += paint(runCell, run);
      run = "";
    }
    runCell = cell;
    run += cell.ch;
  }
  return line + paint(runCell, run);
}

/** The lines install.sh sources between its markers: one variable per colour variant, a row per line. */
function installerBlock(pixels) {
  const palette = ansi256Palette();
  const variable = (variant) => {
    const rows = [];
    for (let y = 0; y < pixels.length; y += 2) {
      rows.push(installerLine(pixels[y], pixels[y + 1] ?? "", variant, palette));
    }
    return `LOGO_${variant.toUpperCase()}='${rows.join("\n")}'`;
  };
  return [
    BEGIN_MARKER,
    `LOGO_WIDTH=${pixels[0].length}`,
    ...["truecolor", "ansi256", "plain"].map(variable),
    END_MARKER,
  ].join("\n");
}

/** install.sh with the text between its markers replaced by the baked logo. */
function installerSource(source, pixels) {
  const begin = source.indexOf(BEGIN_MARKER);
  const end = source.indexOf(END_MARKER);
  if (begin < 0 || end < begin) throw new Error("install.sh is missing its generated-logo markers");
  return source.slice(0, begin) + installerBlock(pixels) + source.slice(end + END_MARKER.length);
}

const pixels = pixelRows(bake(LOGO_LINES * 2));
const installerPath = process.argv[3] ?? DEFAULT_INSTALLER;
writeFileSync(process.argv[2] ?? DEFAULT_OUTPUT, moduleSource(pixels));
writeFileSync(installerPath, installerSource(readFileSync(installerPath, "utf8"), pixels));
