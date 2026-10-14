import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { chromium, type Page } from "@playwright/test";
import tailwindColors from "tailwindcss/colors";
import type { DomElement, DomSnapshot, Rect } from "./dom";

/**
 * Element-level style diff of a visual-diff run: matches the base and head DOM
 * snapshots (dom/<id>.<side>.json) by structural key, ranks what changed and
 * writes changes.md plus zoomed base | head crops of the top changes.
 * Usage: node e2e/visual/styles.ts <out-dir> <base-label> <head-label>
 */

type Category =
  | "border toggled"
  | "element"
  | "border"
  | "background"
  | "spacing"
  | "typography"
  | "size";

const CATEGORY_RANK: Record<Category, number> = {
  "border toggled": 0,
  element: 1,
  border: 2,
  background: 3,
  spacing: 4,
  typography: 5,
  size: 6,
};

interface Line {
  category: Category;
  text: string;
}

interface Occurrence {
  base?: DomElement;
  head?: DomElement;
  /** The element the change is reported against: head's when it exists, else base's. */
  subject: DomElement;
}

interface Group {
  category: Category;
  text: string;
  occurrences: Occurrence[];
}

interface SummaryItem {
  title: string;
  outcome: string;
  images: { base?: string; head?: string };
}

const SIDES = ["top", "right", "bottom", "left"] as const;
const CORNERS = [
  "top-left",
  "top-right",
  "bottom-right",
  "bottom-left",
] as const;
const SIZE_THRESHOLD_PX = 4;
const CROPS_PER_SURFACE = 8;
const GROUPS_LISTED_PER_SURFACE = 50;
const CROP_CONTEXT_PX = 24;
const CROP_ZOOM = 2;
const CROP_PANEL_MAX_PX = 640;
const CROP_SOURCE_MAX_HEIGHT_PX = 400;
const COLOR_FUNCTION = /(?:rgba?|oklch|oklab|lab|lch|hsla?|color)\([^()]*\)/g;
const TRANSPARENT = "rgba(0, 0, 0, 0)";

/** Map each Tailwind palette color to the exact string Chromium computes for it. */
async function resolvePalette(page: Page): Promise<Map<string, string>> {
  const entries: [string, string][] = [];
  for (const [family, shades] of Object.entries(tailwindColors)) {
    if (typeof shades === "string") entries.push([family, shades]);
    else
      for (const [shade, value] of Object.entries(shades))
        entries.push([`${family}-${shade}`, value]);
  }
  const computed = await page.evaluate((pairs) => {
    const probe = document.createElement("div");
    document.body.append(probe);
    return pairs.map(([name, value]) => {
      probe.style.color = "";
      probe.style.color = value;
      return [getComputedStyle(probe).color, name] as const;
    });
  }, entries);
  const palette = new Map<string, string>(computed);
  palette.set(TRANSPARENT, "transparent");
  return palette;
}

/** Replace exact palette colors in a computed value with their Tailwind names. */
function named(value: string, palette: Map<string, string>): string {
  return value.replace(COLOR_FUNCTION, (color) => {
    const exact = palette.get(color);
    if (exact) return exact;
    const alpha = color.match(/^(\w+\(.*?) \/ ([\d.]+)\)$/);
    const opaque = alpha && palette.get(`${alpha[1]})`);
    return opaque ? `${opaque}/${Math.round(Number(alpha[2]) * 100)}` : color;
  });
}

/** CSS shorthand for four box values: "16px", "8px 16px" or all four. */
function box(values: string[]): string {
  const [top, right, bottom, left] = values;
  if (values.every((v) => v === top)) return top;
  if (top === bottom && right === left) return `${top} ${right}`;
  return values.join(" ");
}

function borderSide(
  styles: Record<string, string>,
  side: string,
  palette: Map<string, string>,
): string {
  const style = styles[`border-${side}-style`];
  const width = styles[`border-${side}-width`];
  if (style === "none" || style === "hidden" || width === "0px") return "none";
  return `${style} ${width} ${named(styles[`border-${side}-color`], palette)}`;
}

function outline(styles: Record<string, string>): string {
  const style = styles["outline-style"];
  const width = styles["outline-width"];
  return style === "none" || width === "0px" ? "none" : `${style} ${width}`;
}

function hasBorder(styles: Record<string, string>): boolean {
  return SIDES.some((side) => {
    const style = styles[`border-${side}-style`];
    return (
      style !== "none" &&
      style !== "hidden" &&
      styles[`border-${side}-width`] !== "0px"
    );
  });
}

/** Every style change of one matched element, one line per property family. */
function describe(
  base: DomElement,
  head: DomElement,
  palette: Map<string, string>,
): Line[] {
  const lines: Line[] = [];
  const push = (
    category: Category,
    property: string,
    from: string,
    to: string,
  ) => {
    if (from !== to)
      lines.push({ category, text: `${property} ${from} → ${to}` });
  };
  const toggled = (from: string, to: string): Category =>
    from === "none" || to === "none" ? "border toggled" : "border";

  const baseBorders = SIDES.map((side) =>
    borderSide(base.styles, side, palette),
  );
  const headBorders = SIDES.map((side) =>
    borderSide(head.styles, side, palette),
  );
  if (
    baseBorders.every((b) => b === baseBorders[0]) &&
    headBorders.every((b) => b === headBorders[0])
  ) {
    push(
      toggled(baseBorders[0], headBorders[0]),
      "border",
      baseBorders[0],
      headBorders[0],
    );
  } else {
    SIDES.forEach((side, i) => {
      push(
        toggled(baseBorders[i], headBorders[i]),
        `border-${side}`,
        baseBorders[i],
        headBorders[i],
      );
    });
  }
  const baseOutline = outline(base.styles);
  const headOutline = outline(head.styles);
  push(toggled(baseOutline, headOutline), "outline", baseOutline, headOutline);
  const baseShadow = named(base.styles["box-shadow"], palette);
  const headShadow = named(head.styles["box-shadow"], palette);
  push(toggled(baseShadow, headShadow), "shadow", baseShadow, headShadow);
  const radius = (el: DomElement) =>
    box(CORNERS.map((corner) => el.styles[`border-${corner}-radius`]));
  push("border", "radius", radius(base), radius(head));

  push(
    "background",
    "background",
    named(base.styles["background-color"], palette),
    named(head.styles["background-color"], palette),
  );
  push(
    "background",
    "background-image",
    base.styles["background-image"],
    head.styles["background-image"],
  );

  for (const property of ["padding", "margin"]) {
    const values = (el: DomElement) =>
      box(SIDES.map((side) => el.styles[`${property}-${side}`]));
    push("spacing", property, values(base), values(head));
  }
  push("spacing", "gap", base.styles.gap, head.styles.gap);

  for (const property of [
    "font-size",
    "font-weight",
    "line-height",
    "letter-spacing",
    "opacity",
  ]) {
    push("typography", property, base.styles[property], head.styles[property]);
  }
  push(
    "typography",
    "color",
    named(base.styles.color, palette),
    named(head.styles.color, palette),
  );
  return lines;
}

function sizeLine(base: Rect, head: Rect): Line | null {
  const grew =
    Math.abs(base.width - head.width) >= SIZE_THRESHOLD_PX ||
    Math.abs(base.height - head.height) >= SIZE_THRESHOLD_PX;
  return grew
    ? {
        category: "size",
        text: `size ${base.width}×${base.height} → ${head.width}×${head.height}`,
      }
    : null;
}

const keyOf = (el: DomElement) => `${el.path}|${el.label}`;
const parentPath = (path: string) => path.slice(0, path.lastIndexOf(">"));

function describeElement(el: DomElement): string {
  const tag = el.path.slice(el.path.lastIndexOf(">") + 1).split(":")[0];
  return el.label ? `${tag} "${el.label}"` : tag;
}

/** Elements on one side only that a reader would notice, topmost of each added or removed subtree. */
function unmatched(
  from: DomElement[],
  other: Map<string, DomElement>,
): DomElement[] {
  const missing = from.filter((el) => !other.has(keyOf(el)));
  const missingPaths = new Set(missing.map((el) => el.path));
  return missing.filter(
    (el) =>
      !missingPaths.has(parentPath(el.path)) &&
      (el.label !== "" ||
        hasBorder(el.styles) ||
        el.styles["background-color"] !== TRANSPARENT ||
        el.styles["background-image"] === "set"),
  );
}

/** Collapse identical change sets across elements, highest priority and most frequent first. */
function groupChanges(
  base: DomSnapshot,
  head: DomSnapshot,
  palette: Map<string, string>,
): Group[] {
  const groups = new Map<string, Group>();
  const add = (category: Category, text: string, occurrence: Occurrence) => {
    const key = `${category}|${text}`;
    const group = groups.get(key) ?? { category, text, occurrences: [] };
    group.occurrences.push(occurrence);
    groups.set(key, group);
  };
  const baseByKey = new Map(base.elements.map((el) => [keyOf(el), el]));
  const headByKey = new Map(head.elements.map((el) => [keyOf(el), el]));
  for (const headEl of head.elements) {
    const baseEl = baseByKey.get(keyOf(headEl));
    if (!baseEl) continue;
    const lines = describe(baseEl, headEl, palette);
    if (lines.length > 0) {
      const top = lines.reduce((a, b) =>
        CATEGORY_RANK[b.category] < CATEGORY_RANK[a.category] ? b : a,
      );
      add(top.category, lines.map((line) => line.text).join("; "), {
        base: baseEl,
        head: headEl,
        subject: headEl,
      });
    }
    const size = sizeLine(baseEl.rect, headEl.rect);
    if (size)
      add(size.category, size.text, {
        base: baseEl,
        head: headEl,
        subject: headEl,
      });
  }
  for (const el of unmatched(base.elements, headByKey))
    add("element", `removed ${describeElement(el)}`, { base: el, subject: el });
  for (const el of unmatched(head.elements, baseByKey))
    add("element", `added ${describeElement(el)}`, { head: el, subject: el });
  return [...groups.values()].sort(
    (a, b) =>
      CATEGORY_RANK[a.category] - CATEGORY_RANK[b.category] ||
      b.occurrences.length - a.occurrences.length ||
      a.text.localeCompare(b.text),
  );
}

// PNG stores width and height as big-endian uint32s at bytes 16 and 20.
function pngSize(path: string): { width: number; height: number } {
  const header = readFileSync(path).subarray(16, 24);
  return { width: header.readUInt32BE(0), height: header.readUInt32BE(4) };
}

interface Screenshot {
  uri: string;
  width: number;
  height: number;
}

function loadScreenshot(path: string | undefined): Screenshot | null {
  if (!path || !existsSync(path)) return null;
  return {
    uri: `data:image/png;base64,${readFileSync(path).toString("base64")}`,
    ...pngSize(path),
  };
}

const repeats = (group: Group) =>
  group.occurrences.length > 1 ? ` ×${group.occurrences.length} elements` : "";

const escapeHtml = (text: string) =>
  text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

interface Crop {
  shot: Screenshot;
  el: DomElement;
  region: Rect;
}

/** The screenshot region around an element's own rect, or null when it was not captured. */
function cropOf(
  shot: Screenshot | null,
  el: DomElement | undefined,
): Crop | null {
  if (!shot || !el || el.rect.y >= shot.height || el.rect.x >= shot.width)
    return null;
  const x = Math.max(0, el.rect.x - CROP_CONTEXT_PX);
  const y = Math.max(0, el.rect.y - CROP_CONTEXT_PX);
  const width =
    Math.min(shot.width, el.rect.x + el.rect.width + CROP_CONTEXT_PX) - x;
  const height =
    Math.min(
      shot.height,
      el.rect.y + el.rect.height + CROP_CONTEXT_PX,
      y + CROP_SOURCE_MAX_HEIGHT_PX,
    ) - y;
  return { shot, el, region: { x, y, width, height } };
}

/** One side's zoomed crop with the element outlined. */
function cropPanel(
  label: string,
  crop: Crop | null,
  missing: string,
  zoom: number,
): string {
  const caption = `<figcaption>${escapeHtml(label)}</figcaption>`;
  if (!crop) return `<figure>${caption}<p>${missing}</p></figure>`;
  const { shot, el, region } = crop;
  const px = (value: number) => `${Math.round(value * zoom)}px`;
  return `<figure>${caption}<div class="crop" style="width:${px(region.width)};height:${px(region.height)};background-image:url(${shot.uri});background-size:${px(shot.width)} ${px(shot.height)};background-position:-${px(region.x)} -${px(region.y)}"><div class="target" style="left:${px(el.rect.x - region.x)};top:${px(el.rect.y - region.y)};width:${px(el.rect.width)};height:${px(el.rect.height)}"></div></div></figure>`;
}

function cropHtml(
  title: string,
  group: Group,
  base: Screenshot | null,
  head: Screenshot | null,
  labels: [string, string],
): string {
  const { base: baseEl, head: headEl, subject } = group.occurrences[0];
  const changes = group.text
    .split("; ")
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  const baseCrop = cropOf(base, baseEl);
  const headCrop = cropOf(head, headEl);
  // One zoom for both panels so sizes compare at a glance.
  const widest = Math.max(
    baseCrop?.region.width ?? 0,
    headCrop?.region.width ?? 0,
  );
  const zoom = Math.min(CROP_ZOOM, CROP_PANEL_MAX_PX / Math.max(widest, 1));
  const missing = (el: DomElement | undefined) =>
    el ? "outside the captured screenshot" : "absent on this side";
  return `<!doctype html><html><head><style>
    body{margin:0;background:#18181b;color:#e4e4e7;font:14px system-ui}
    #card{display:inline-block;padding:16px}
    h1{font-size:15px;margin:0 0 4px}
    ul{margin:0 0 12px;padding-left:18px;color:#d4d4d8}
    main{display:flex;gap:16px;align-items:flex-start}
    figure{margin:0}
    figcaption{margin-bottom:6px;color:#a1a1aa}
    p{margin:0;color:#71717a}
    .crop{position:relative;background-repeat:no-repeat;image-rendering:pixelated;background-color:#000}
    .target{position:absolute;outline:1px dotted #f0abfc;outline-offset:4px}
  </style></head><body><div id="card"><h1>${escapeHtml(`${title} · ${describeElement(subject)}${repeats(group)}`)}</h1><ul>${changes}</ul><main>${cropPanel(
    `Before · ${labels[0]}`,
    baseCrop,
    missing(baseEl),
    zoom,
  )}${cropPanel(`After · ${labels[1]}`, headCrop, missing(headEl), zoom)}</main></div></body></html>`;
}

function readSnapshot(path: string): DomSnapshot | null {
  return existsSync(path)
    ? (JSON.parse(readFileSync(path, "utf8")) as DomSnapshot)
    : null;
}

async function main(): Promise<void> {
  const [outDir, baseLabel = "base", headLabel = "head"] =
    process.argv.slice(2);
  if (!outDir)
    throw new Error("usage: styles.ts <out-dir> [base-label] [head-label]");
  const domDir = join(outDir, "dom");
  const changesDir = join(outDir, "changes");
  mkdirSync(changesDir, { recursive: true });
  const summaryPath = join(outDir, "summary.json");
  const summary = existsSync(summaryPath)
    ? (JSON.parse(readFileSync(summaryPath, "utf8")) as SummaryItem[])
    : [];
  const ids = existsSync(domDir)
    ? readdirSync(domDir)
        .filter((file) => file.endsWith(".head.json"))
        .map((file) => file.slice(0, -".head.json".length))
        .sort((a, b) => a.localeCompare(b))
    : [];

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: CROP_PANEL_MAX_PX * 2 + 80, height: 600 },
  });
  const palette = await resolvePalette(page);
  const sections: string[] = [];
  let compared = 0;
  for (const id of ids) {
    const base = readSnapshot(join(domDir, `${id}.base.json`));
    const head = readSnapshot(join(domDir, `${id}.head.json`));
    if (!base || !head) continue;
    compared += 1;
    const groups = groupChanges(base, head, palette);
    if (groups.length === 0) continue;

    const basePath = join(outDir, "baseline", `${id}.png`);
    const item = summary.find((entry) => entry.title === head.title);
    const baseShot = loadScreenshot(basePath);
    const headShot = loadScreenshot(
      item?.images.head ??
        (item?.outcome === "unchanged" ? basePath : undefined),
    );
    const lines: string[] = [];
    for (const [index, group] of groups
      .slice(0, GROUPS_LISTED_PER_SURFACE)
      .entries()) {
      let crop = "";
      if (index < CROPS_PER_SURFACE) {
        const file = `${id}-${index + 1}.png`;
        await page.setContent(
          cropHtml(head.title, group, baseShot, headShot, [
            baseLabel,
            headLabel,
          ]),
          { waitUntil: "load" },
        );
        await page
          .locator("#card")
          .screenshot({ path: join(changesDir, file) });
        crop = ` · [crop](changes/${file})`;
      }
      const subject = describeElement(group.occurrences[0].subject);
      lines.push(
        `- **${group.category}** ${group.text}${repeats(group)} · \`${subject}\`${crop}`,
      );
    }
    const hidden = groups.length - GROUPS_LISTED_PER_SURFACE;
    if (hidden > 0) lines.push(`- …and ${hidden} more`);
    const truncated =
      base.truncated || head.truncated
        ? "\n\nSnapshot capped at its element limit; later elements are not compared."
        : "";
    sections.push(`## \`${head.title}\`${truncated}\n\n${lines.join("\n")}\n`);
  }
  await browser.close();

  const changed = sections.length;
  writeFileSync(
    join(outDir, "changes.md"),
    [
      `# Style changes: ${baseLabel} → ${headLabel}`,
      "",
      `${compared} surfaces compared · ${changed} with element-level changes. Elements are matched by structural path and own text; position shifts alone are ignored.`,
      "",
      ...(changed ? sections : ["No element-level style changes."]),
    ].join("\n"),
  );
  console.info(
    `style diff: ${compared} surfaces compared, ${changed} with changes`,
  );
}

await main();
