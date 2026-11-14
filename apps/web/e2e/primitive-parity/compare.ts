import type { Capture, Styles } from "./capture";

export interface Difference {
  key: string;
  prop: string;
  v2: string;
  v3: string;
}

export interface Approval {
  key: string;
  prop: string;
  reason: string;
}

const PX_TOLERANCE = 1;
const COLOUR_TOLERANCE = 2;
const MS_TOLERANCE = 10;
const UNITLESS_TOLERANCE = 0.02;
const SIDES = ["top", "right", "bottom", "left"] as const;
const FADING_KINDS = ["button", "buttongroup"];

type Rgba = [number, number, number, number];

const toByte = (linear: number) => {
  const clamped = Math.min(1, Math.max(0, linear));
  const encoded =
    clamped <= 0.0031308
      ? 12.92 * clamped
      : 1.055 * clamped ** (1 / 2.4) - 0.055;
  return encoded * 255;
};

const multiply = (m: number[], v: number[]) => [
  m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
  m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
  m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
];

function oklabToRgb(l: number, a: number, b: number): number[] {
  const lms = [
    (l + 0.3963377774 * a + 0.2158037573 * b) ** 3,
    (l - 0.1055613458 * a - 0.0638541728 * b) ** 3,
    (l - 0.0894841775 * a - 1.291485548 * b) ** 3,
  ];
  return multiply(
    [
      4.0767416621, -3.3077115913, 0.2309699292, -1.2684380046, 2.6097574011,
      -0.3413193965, -0.0041960863, -0.7034186147, 1.707614701,
    ],
    lms,
  ).map(toByte);
}

function labToRgb(l: number, a: number, b: number): number[] {
  const epsilon = 216 / 24389;
  const kappa = 24389 / 27;
  const fy = (l + 16) / 116;
  const fx = fy + a / 500;
  const fz = fy - b / 200;
  const cube = (f: number) =>
    f ** 3 > epsilon ? f ** 3 : (116 * f - 16) / kappa;
  const xyzD50 = [
    (cube(fx) * 0.3457) / 0.3585,
    l > kappa * epsilon ? fy ** 3 : l / kappa,
    (cube(fz) * (1 - 0.3457 - 0.3585)) / 0.3585,
  ];
  const xyzD65 = multiply(
    [
      0.9554734527042182, -0.023098536874261423, 0.0632593086610217,
      -0.028369706963208136, 1.0099954580058226, 0.021041398966943008,
      0.012314001688319899, -0.020507696433477912, 1.3303659366080753,
    ],
    xyzD50,
  );
  return multiply(
    [
      3.2409699419045226, -1.537383177570094, -0.4986107602930034,
      -0.9692436362808796, 1.8759675015077202, 0.04155505740717559,
      0.05563007969699366, -0.20397695888897652, 1.0569715142428786,
    ],
    xyzD65,
  ).map(toByte);
}

const num = (token: string, percentScale = 1) =>
  token.endsWith("%")
    ? (Number.parseFloat(token) / 100) * percentScale
    : Number.parseFloat(token);

/** A computed colour of any notation Chrome serialises, as sRGB bytes and alpha on 0-255; null if not a colour. */
export function parseColour(value: string): Rgba | null {
  const match = /^(rgba?|oklab|oklch|lab|lch|color)\((.*)\)$/.exec(
    value.trim(),
  );
  if (!match) return value === "transparent" ? [0, 0, 0, 0] : null;
  const [fn, body] = [match[1], match[2]];
  const [channelPart, alphaPart] = body.split("/");
  const channels = channelPart.replace(/,/g, " ").trim().split(/\s+/);
  let alpha = alphaPart === undefined ? 1 : num(alphaPart.trim());
  if (fn === "rgb" || fn === "rgba") {
    if (channels.length === 4) alpha = num(channels[3]);
    return [num(channels[0]), num(channels[1]), num(channels[2]), alpha * 255];
  }
  if (fn === "color") {
    const [space, r, g, b] = channels;
    if (space !== "srgb") return null;
    return [num(r) * 255, num(g) * 255, num(b) * 255, alpha * 255];
  }
  const [l, c1, c2] = channels;
  if (fn === "oklab") {
    return [
      ...oklabToRgb(num(l), num(c1, 0.4), num(c2, 0.4)),
      alpha * 255,
    ] as Rgba;
  }
  if (fn === "oklch") {
    const hue = (num(c2) * Math.PI) / 180;
    const chroma = num(c1, 0.4);
    return [
      ...oklabToRgb(num(l), chroma * Math.cos(hue), chroma * Math.sin(hue)),
      alpha * 255,
    ] as Rgba;
  }
  if (fn === "lab") {
    return [
      ...labToRgb(num(l, 100), num(c1, 125), num(c2, 125)),
      alpha * 255,
    ] as Rgba;
  }
  const hue = (num(c2) * Math.PI) / 180;
  const chroma = num(c1, 150);
  return [
    ...labToRgb(num(l, 100), chroma * Math.cos(hue), chroma * Math.sin(hue)),
    alpha * 255,
  ] as Rgba;
}

/** Splits on a separator outside parentheses. */
function splitTop(value: string, separator: RegExp): string[] {
  const out: string[] = [];
  let depth = 0;
  let current = "";
  for (const char of value) {
    if (char === "(") depth++;
    if (char === ")") depth--;
    if (depth === 0 && separator.test(char)) {
      if (current.trim()) out.push(current.trim());
      current = "";
    } else current += char;
  }
  if (current.trim()) out.push(current.trim());
  return out;
}

function tokenEqual(a: string, b: string): boolean {
  if (a === b) return true;
  const ca = parseColour(a);
  const cb = parseColour(b);
  if (ca && cb) {
    if (ca[3] <= COLOUR_TOLERANCE && cb[3] <= COLOUR_TOLERANCE) return true;
    return ca.every(
      (channel, i) => Math.abs(channel - cb[i]) <= COLOUR_TOLERANCE,
    );
  }
  const time = (t: string) =>
    /^-?[\d.]+m?s$/.test(t)
      ? Number.parseFloat(t) * (t.endsWith("ms") ? 1 : 1000)
      : null;
  const [ta, tb] = [time(a), time(b)];
  if (ta !== null && tb !== null) return Math.abs(ta - tb) <= MS_TOLERANCE;
  if (/^-?[\d.]+px$/.test(a) && /^-?[\d.]+px$/.test(b)) {
    // inclusive, past float noise: a 6.6px gap against 7.6px is within 1px
    return (
      Math.abs(Number.parseFloat(a) - Number.parseFloat(b)) <=
      PX_TOLERANCE + 0.01
    );
  }
  if (/^-?[\d.]+$/.test(a) && /^-?[\d.]+$/.test(b)) {
    return Math.abs(Number(a) - Number(b)) <= UNITLESS_TOLERANCE;
  }
  return false;
}

/** A shadow list without the layers that draw nothing (transparent, or zero offset, blur and spread). */
function visibleShadows(value: string): string[] {
  if (value === "none") return [];
  return splitTop(value, /,/).filter((layer) => {
    const tokens = splitTop(layer, /\s/);
    const colour = tokens.map(parseColour).find(Boolean);
    if (colour && colour[3] <= COLOUR_TOLERANCE) return false;
    const lengths = tokens.filter((t) => /px$/.test(t));
    return lengths.some((t) => Number.parseFloat(t) !== 0);
  });
}

function valuesEqual(prop: string, a: string, b: string): boolean {
  if (a === b) return true;
  // a flex or grid gap of normal is 0
  if (prop.endsWith("-gap")) {
    return valuesEqual(
      "gap",
      a.replace("normal", "0px"),
      b.replace("normal", "0px"),
    );
  }
  if (prop === "box-shadow") {
    const [la, lb] = [visibleShadows(a), visibleShadows(b)];
    return (
      la.length === lb.length &&
      la.every((layer, i) => {
        const [ta, tb] = [splitTop(layer, /\s/), splitTop(lb[i], /\s/)];
        return (
          ta.length === tb.length && ta.every((t, j) => tokenEqual(t, tb[j]))
        );
      })
    );
  }
  const [la, lb] = [splitTop(a, /[\s,]/), splitTop(b, /[\s,]/)];
  return la.length === lb.length && la.every((t, i) => tokenEqual(t, lb[i]));
}

/** Drops what the eye cannot see: a border or outline with no style, width or colour draws nothing. */
function visible(styles: Styles): Styles {
  const out = { ...styles };
  const clear = (colour: string | undefined) =>
    (parseColour(colour ?? "")?.[3] ?? 255) <= COLOUR_TOLERANCE;
  for (const side of SIDES) {
    if (
      ["none", "hidden"].includes(out[`border-${side}-style`] ?? "") ||
      out[`border-${side}-width`] === "0px" ||
      clear(out[`border-${side}-color`])
    ) {
      out[`border-${side}-width`] = "0px";
      out[`border-${side}-style`] = "none";
      out[`border-${side}-color`] = "n/a";
    }
  }
  // corners only show on a box that draws something
  const draws =
    !clear(out["background-color"]) ||
    SIDES.some((side) => out[`border-${side}-width`] !== "0px") ||
    visibleShadows(out["box-shadow"] ?? "none").length > 0;
  if (!draws) {
    for (const corner of [
      "top-left",
      "top-right",
      "bottom-right",
      "bottom-left",
    ]) {
      out[`border-${corner}-radius`] = "n/a";
    }
  }
  if (
    out["outline-style"] === "none" ||
    out["outline-width"] === "0px" ||
    clear(out["outline-color"])
  ) {
    out["outline-style"] = "none";
    out["outline-width"] = "0px";
    out["outline-color"] = "n/a";
    out["outline-offset"] = "n/a";
  }
  return out;
}

const TYPE_ONLY = [
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
  "color",
  "text-x",
  "text-y",
];
/** A text part is the element holding the text, a different box on each side, so only its type and position compare. */
const PART_PROPS: Record<string, string[]> = {
  text: TYPE_ONLY,
  value: TYPE_ONLY,
  title: TYPE_ONLY,
  label: TYPE_ONLY,
};

/** Every property of every part v2 drew that v3 draws differently, beyond the tolerances. */
export function compareCaptures(v2: Capture, v3: Capture): Difference[] {
  const out: Difference[] = [];
  for (const [key, rawV2] of Object.entries(v2)) {
    const rawV3 = v3[key];
    if (!rawV3 || rawV3.missing || rawV2.missing) {
      if (rawV2.missing !== rawV3?.missing) {
        out.push({
          key,
          prop: "(part)",
          v2: rawV2.missing ? "missing" : "present",
          v3: rawV3 && !rawV3.missing ? "present" : "missing",
        });
      }
      continue;
    }
    const [a, b] = [visible(rawV2), visible(rawV3)];
    const only = PART_PROPS[key.split("::")[1].replace(/\d+$/, "")];
    for (const [prop, value] of Object.entries(a)) {
      if (only && !only.includes(prop)) continue;
      // n/a on one side: the other version draws this on a different element of the part
      if (value === "n/a" || b[prop] === "n/a") continue;
      // text-x/y exist only where the part itself holds the text
      if (prop.startsWith("text-") && b[prop] === undefined) continue;
      // insets compare through text-x/y and the parts' offsets: padding sits on different elements per version
      if (prop.startsWith("padding-")) continue;
      // a fade shows on a control's fill; on every other part the property it times never changes
      if (
        prop === "transition-duration" &&
        !FADING_KINDS.includes(key.split("/")[0])
      ) {
        continue;
      }
      if (!valuesEqual(prop, value, b[prop] ?? "")) {
        out.push({ key, prop, v2: value, v3: b[prop] ?? "" });
      }
    }
  }
  return out;
}

export const isApproved = (difference: Difference, approvals: Approval[]) =>
  approvals.some(
    (approval) =>
      new RegExp(`^${approval.key}$`).test(difference.key) &&
      new RegExp(`^${approval.prop}$`).test(difference.prop),
  );
