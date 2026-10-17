// Rasterise apps/web/public/brand/gaia_logo.svg into per-pixel fill classes for bake-logo.mjs.
import { readFileSync } from "node:fs";
import { Resvg } from "@resvg/resvg-js";

const SVG_PATH = new URL("../../../apps/web/public/brand/gaia_logo.svg", import.meta.url);
const SOURCE = readFileSync(SVG_PATH, "utf8");
const VIEWBOX = SOURCE.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
export const VB_W = VIEWBOX[2];
export const VB_H = VIEWBOX[3];

// The logo's fills, in the order a pixel class index refers to them; `key` is the generated table's letter.
export const FILLS = [
  { key: "d", hex: "#0f537c" },
  { key: "m", hex: "#059cda" },
  { key: "l", hex: "#02bdff" },
];

/** "#rrggbb" as [r, g, b]. */
export function hexRgb(hex) {
  return [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
}

const RGB = FILLS.map((f) => hexRgb(f.hex));

/**
 * Render a window of the vector aliased (crispEdges), so every pixel is exactly one fill or empty.
 * The window is [x, y, w, h] in viewBox units; the output is pw x ph classes, -1 for empty.
 */
export function renderClasses([x, y, w, h], pw, ph) {
  const svg = SOURCE.replace(
    /viewBox="[^"]+"/,
    `viewBox="${x} ${y} ${w} ${h}" preserveAspectRatio="none" width="${pw}" height="${ph}"`,
  );
  const px = new Resvg(svg, { shapeRendering: 1, fitTo: { mode: "original" } }).render().pixels;
  const out = new Int8Array(pw * ph).fill(-1);
  for (let i = 0; i < pw * ph; i++) {
    if (px[i * 4 + 3] < 128) continue;
    let best = 0;
    let bestD = Number.POSITIVE_INFINITY;
    for (let k = 0; k < RGB.length; k++) {
      const d =
        (RGB[k][0] - px[i * 4]) ** 2 + (RGB[k][1] - px[i * 4 + 1]) ** 2 + (RGB[k][2] - px[i * 4 + 2]) ** 2;
      if (d < bestD) {
        bestD = d;
        best = k;
      }
    }
    out[i] = best;
  }
  return out;
}
