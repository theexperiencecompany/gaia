import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

/**
 * Names computed CSS colors for the style diff: the nearest Tailwind v4 palette
 * color or project @theme token within a small OKLab distance, else hex.
 */

type Lab = [number, number, number];

interface Color {
  lab: Lab;
  alpha: number;
}

// ΔE in OKLab units; 0.02 is roughly the smallest difference a reader notices.
const MAX_NAMING_DISTANCE = 0.02;
const TAILWIND_THEME = createRequire(import.meta.url).resolve(
  "tailwindcss/theme.css",
);
const PROJECT_THEME = join(
  import.meta.dirname,
  "../../src/app/styles/globals.css",
);
const COLOR_TOKEN = /--color-([\w-]+):\s*([^;]+);/g;
const COLOR_FUNCTION = /(?:rgba?|oklch|oklab|lab|lch|hsla?|color)\([^()]*\)/g;

const toLinear = (channel: number) =>
  channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
const fromLinear = (channel: number) =>
  channel <= 0.0031308 ? channel * 12.92 : 1.055 * channel ** (1 / 2.4) - 0.055;

/** sRGB channels in 0..1 to OKLab (Ottosson's reference matrices). */
function srgbToOklab([r, g, b]: Lab): Lab {
  const [lr, lg, lb] = [r, g, b].map(toLinear);
  const l = Math.cbrt(
    0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb,
  );
  const m = Math.cbrt(
    0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb,
  );
  const s = Math.cbrt(
    0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb,
  );
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

function oklabToSrgb([L, a, b]: Lab): Lab {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((channel) => Math.min(1, Math.max(0, fromLinear(channel)))) as Lab;
}

/** A CSS number token; `percentOf` is what 100% means for this channel. */
function number(token: string | undefined, percentOf: number): number {
  if (token === undefined || token === "none") return 0;
  return token.endsWith("%")
    ? (Number.parseFloat(token) / 100) * percentOf
    : Number.parseFloat(token);
}

function parseHex(hex: string): Color | null {
  const body = hex.slice(1);
  const pairs =
    body.length <= 4
      ? [...body].map((digit) => digit + digit)
      : (body.match(/../g) ?? []);
  if (pairs.length !== 3 && pairs.length !== 4) return null;
  const [r, g, b, alpha = 1] = pairs.map(
    (pair) => Number.parseInt(pair, 16) / 255,
  );
  return { lab: srgbToOklab([r, g, b]), alpha };
}

/** Parse rgb(), oklab(), oklch(), hex or transparent; null for any other color syntax. */
export function parseColor(value: string): Color | null {
  const color = value.trim().toLowerCase();
  if (color === "transparent") return { lab: [0, 0, 0], alpha: 0 };
  if (color.startsWith("#")) return parseHex(color);
  const fn = color.match(/^(rgba?|oklab|oklch)\(([^()]*)\)$/);
  if (!fn) return null;
  const [c1, c2, c3, alphaToken] = fn[2]
    .replace("/", " ")
    .split(/[\s,]+/)
    .filter(Boolean);
  const alpha = alphaToken === undefined ? 1 : number(alphaToken, 1);
  if (fn[1].startsWith("rgb"))
    return {
      lab: srgbToOklab([
        number(c1, 255) / 255,
        number(c2, 255) / 255,
        number(c3, 255) / 255,
      ]),
      alpha,
    };
  const lightness = number(c1, 1);
  if (fn[1] === "oklab")
    return { lab: [lightness, number(c2, 0.4), number(c3, 0.4)], alpha };
  const chroma = number(c2, 0.4);
  const hue = (number(c3, 360) * Math.PI) / 180;
  return {
    lab: [lightness, chroma * Math.cos(hue), chroma * Math.sin(hue)],
    alpha,
  };
}

/** Every literal --color-* token in a stylesheet; references like var() are skipped. */
function tokensOf(css: string): [string, Lab][] {
  return [...css.matchAll(COLOR_TOKEN)].flatMap(([, name, value]) => {
    const color = parseColor(value);
    return color && color.alpha === 1
      ? [[name, color.lab] as [string, Lab]]
      : [];
  });
}

/** The bodies of a stylesheet's @theme blocks. */
function themeBlocks(css: string): string {
  const bodies: string[] = [];
  for (const start of css.matchAll(/@theme[^{]*\{/g)) {
    let depth = 1;
    let end = start.index + start[0].length;
    while (depth > 0 && end < css.length) {
      if (css[end] === "{") depth += 1;
      if (css[end] === "}") depth -= 1;
      end += 1;
    }
    bodies.push(css.slice(start.index + start[0].length, end - 1));
  }
  return bodies.join("\n");
}

// Tailwind first, so on an exact tie the palette name wins over a project alias.
const PALETTE: [string, Lab][] = [
  ...tokensOf(readFileSync(TAILWIND_THEME, "utf8")),
  ...tokensOf(themeBlocks(readFileSync(PROJECT_THEME, "utf8"))),
];

function hex(lab: Lab): string {
  return `#${oklabToSrgb(lab)
    .map((channel) =>
      Math.round(channel * 255)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

function nameOf({ lab, alpha }: Color): string {
  if (alpha === 0) return "transparent";
  let best = hex(lab);
  let bestDistance = MAX_NAMING_DISTANCE;
  for (const [name, candidate] of PALETTE) {
    const distance = Math.hypot(
      lab[0] - candidate[0],
      lab[1] - candidate[1],
      lab[2] - candidate[2],
    );
    if (distance < bestDistance) {
      best = name;
      bestDistance = distance;
    }
  }
  return alpha < 1 ? `${best}/${Math.round(alpha * 100)}` : best;
}

/** Replace every parseable color in a computed value with its palette name or hex. */
export function nameColors(value: string): string {
  return value.replace(COLOR_FUNCTION, (color) => {
    const parsed = parseColor(color);
    return parsed ? nameOf(parsed) : color;
  });
}
