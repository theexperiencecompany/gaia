import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { chromium, type Page } from "@playwright/test";
import { nameColors, parseColor } from "./colors.ts";
import type { DomElement, DomSnapshot, Rect } from "./dom";
import { matchElements, parentPath, tagOf } from "./match.ts";
import {
  loadScreenshot,
  measureVisibility,
  type Screenshot,
  type Visibility,
} from "./pixels.ts";

/**
 * Element-level style diff of a visual-diff run: matches the base and head DOM
 * snapshots (dom/<id>.<side>.json) (see match.ts), checks which changes alter
 * pixels (see pixels.ts) and writes changes.md plus zoomed base | head crops of
 * the largest visible ones.
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

/** A group whose occurrences are ordered most changed pixels first, measured by its first. */
type MeasuredGroup = Group & Visibility;

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
const TRANSPARENT = "rgba(0, 0, 0, 0)";
const COLOR_IN_SHADOW = /^(?:\w+\([^()]*\)|transparent)/;

/** A box-shadow without the transparent and zero-size layers that render nothing, colors named. */
function shadow(value: string): string {
  if (value === "none") return "none";
  const layers = value
    .split(/,(?![^(]*\))/)
    .map((layer) => layer.trim())
    .filter((layer) => {
      const color = layer.match(COLOR_IN_SHADOW)?.[0];
      const visible = !color || parseColor(color)?.alpha !== 0;
      const lengths = layer.match(/-?[\d.]+px/g) ?? [];
      return (
        visible && lengths.some((length) => Number.parseFloat(length) !== 0)
      );
    });
  return layers.length > 0 ? nameColors(layers.join(", ")) : "none";
}

/** CSS shorthand for four box values: "16px", "8px 16px" or all four. */
function box(values: string[]): string {
  const [top, right, bottom, left] = values;
  if (values.every((v) => v === top)) return top;
  if (top === bottom && right === left) return `${top} ${right}`;
  return values.join(" ");
}

function borderSide(styles: Record<string, string>, side: string): string {
  const style = styles[`border-${side}-style`];
  const width = styles[`border-${side}-width`];
  if (style === "none" || style === "hidden" || width === "0px") return "none";
  return `${style} ${width} ${nameColors(styles[`border-${side}-color`])}`;
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
function describe(base: DomElement, head: DomElement): Line[] {
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

  const baseBorders = SIDES.map((side) => borderSide(base.styles, side));
  const headBorders = SIDES.map((side) => borderSide(head.styles, side));
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
  const baseShadow = shadow(base.styles["box-shadow"]);
  const headShadow = shadow(head.styles["box-shadow"]);
  push(toggled(baseShadow, headShadow), "shadow", baseShadow, headShadow);
  const radius = (el: DomElement) =>
    box(CORNERS.map((corner) => el.styles[`border-${corner}-radius`]));
  push("border", "radius", radius(base), radius(head));

  push(
    "background",
    "background",
    nameColors(base.styles["background-color"]),
    nameColors(head.styles["background-color"]),
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
    nameColors(base.styles.color),
    nameColors(head.styles.color),
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

function describeElement(el: DomElement): string {
  const tag = tagOf(el);
  return el.label ? `${tag} "${el.label}"` : tag;
}

// Absent from snapshots captured before animation-name was recorded.
const isAnimated = (el: DomElement) => {
  const name = el.styles["animation-name"];
  return name !== undefined && name !== "none";
};

/** Elements on one side only that a reader would notice, topmost of each added or removed subtree. */
function unmatched(from: DomElement[], paired: Set<DomElement>): DomElement[] {
  const missing = from.filter((el) => !paired.has(el));
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
function groupChanges(base: DomSnapshot, head: DomSnapshot): Group[] {
  const groups = new Map<string, Group>();
  const add = (category: Category, text: string, occurrence: Occurrence) => {
    const key = `${category}|${text}`;
    const group = groups.get(key) ?? { category, text, occurrences: [] };
    group.occurrences.push(occurrence);
    groups.set(key, group);
  };
  const pairs = matchElements(base.elements, head.elements);
  for (const [baseEl, headEl] of pairs) {
    // A running animation's computed values are whatever frame the capture landed on.
    if (isAnimated(baseEl) || isAnimated(headEl)) continue;
    const occurrence = { base: baseEl, head: headEl, subject: headEl };
    const lines = describe(baseEl, headEl);
    if (lines.length > 0) {
      const top = lines.reduce((a, b) =>
        CATEGORY_RANK[b.category] < CATEGORY_RANK[a.category] ? b : a,
      );
      add(top.category, lines.map((line) => line.text).join("; "), occurrence);
    }
    const size = sizeLine(baseEl.rect, headEl.rect);
    if (size) add(size.category, size.text, occurrence);
  }
  for (const el of unmatched(base.elements, new Set(pairs.keys())))
    add("element", `removed ${describeElement(el)}`, { base: el, subject: el });
  for (const el of unmatched(head.elements, new Set(pairs.values())))
    add("element", `added ${describeElement(el)}`, { head: el, subject: el });
  return [...groups.values()].sort(
    (a, b) =>
      CATEGORY_RANK[a.category] - CATEGORY_RANK[b.category] ||
      b.occurrences.length - a.occurrences.length ||
      a.text.localeCompare(b.text),
  );
}

/** Each group's pixel visibility; an unchanged surface's screenshots match, so nothing shows. */
async function measureGroups(
  page: Page,
  groups: Group[],
  shots: { base: Screenshot; head: Screenshot } | null,
): Promise<MeasuredGroup[]> {
  if (!shots)
    return groups.map((group) => ({
      ...group,
      visible: false,
      changedPixels: 0,
    }));
  const occurrences = groups.flatMap((group) => group.occurrences);
  const measured = await measureVisibility(
    page,
    shots.base,
    shots.head,
    occurrences.map(({ base, head, subject }) => ({
      base: (base ?? subject).rect,
      head: (head ?? subject).rect,
    })),
  );
  let offset = 0;
  return groups.map((group) => {
    const ranked = group.occurrences
      .map((occurrence, i) => ({ occurrence, ...measured[offset + i] }))
      .sort((a, b) => b.changedPixels - a.changedPixels);
    offset += group.occurrences.length;
    return {
      ...group,
      occurrences: ranked.map(({ occurrence }) => occurrence),
      visible: ranked.some(({ visible }) => visible),
      // The largest occurrence, not the sum: repeated elements are often nested wrappers.
      changedPixels: ranked[0].changedPixels,
    };
  });
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
function cropOf(shot: Screenshot, el: DomElement | undefined): Crop | null {
  if (!el || el.rect.y >= shot.height || el.rect.x >= shot.width) return null;
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
  base: Screenshot,
  head: Screenshot,
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

function changeLine(group: MeasuredGroup, crop: string): string {
  const subject = describeElement(group.occurrences[0].subject);
  const pixels = group.visible ? ` (${group.changedPixels} px changed)` : "";
  return `- **${group.category}** ${group.text}${repeats(group)} · \`${subject}\`${pixels}${crop}`;
}

/** A surface's changes: visible ones by changed pixels, the computed-only rest folded under a details block. */
function surfaceSection(
  base: DomSnapshot,
  head: DomSnapshot,
  visible: string[],
  computedOnly: MeasuredGroup[],
): string {
  const rest = computedOnly
    .slice(0, GROUPS_LISTED_PER_SURFACE)
    .map((group) => changeLine(group, ""));
  const hidden = computedOnly.length - GROUPS_LISTED_PER_SURFACE;
  if (hidden > 0) rest.push(`- …and ${hidden} more`);
  const folded =
    rest.length > 0
      ? `<details><summary>${computedOnly.length} computed-only changes (no pixel difference)</summary>\n\n${rest.join("\n")}\n\n</details>`
      : "";
  const truncated =
    base.truncated || head.truncated
      ? "\n\nSnapshot capped at its element limit; later elements are not compared."
      : "";
  const body = [visible.join("\n"), folded].filter(Boolean).join("\n\n");
  return `## \`${head.title}\`${truncated}\n\n${body}\n`;
}

/** Both screenshots of a changed surface; null when the surface is unchanged and they match. */
function screenshotsOf(
  item: SummaryItem | undefined,
  title: string,
): { base: Screenshot; head: Screenshot } | null {
  if (item?.outcome === "unchanged") return null;
  const { base, head } = item?.images ?? {};
  if (!base || !head)
    throw new Error(`${title}: summary.json lists no base and head screenshot`);
  return { base: loadScreenshot(base), head: loadScreenshot(head) };
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
  const sections: string[] = [];
  const counts: string[] = [];
  let compared = 0;
  let visibleTotal = 0;
  let computedOnlyTotal = 0;
  for (const id of ids) {
    const base = readSnapshot(join(domDir, `${id}.base.json`));
    const head = readSnapshot(join(domDir, `${id}.head.json`));
    if (!base || !head) continue;
    compared += 1;
    const groups = groupChanges(base, head);
    if (groups.length === 0) continue;

    const item = summary.find((entry) => entry.title === head.title);
    const shots = screenshotsOf(item, head.title);
    const measured = await measureGroups(page, groups, shots);
    // A container that grew because its content grew is a consequence, so style
    // changes rank before size changes; pixel count orders within a category.
    const visible = measured
      .filter((group) => group.visible)
      .sort(
        (a, b) =>
          CATEGORY_RANK[a.category] - CATEGORY_RANK[b.category] ||
          b.changedPixels - a.changedPixels,
      );
    const computedOnly = measured.filter((group) => !group.visible);
    const lines: string[] = [];
    for (const [index, group] of visible.entries()) {
      if (!shots || index >= CROPS_PER_SURFACE) {
        lines.push(changeLine(group, ""));
        continue;
      }
      const file = `${id}-${index + 1}.png`;
      await page.setContent(
        cropHtml(head.title, group, shots.base, shots.head, [
          baseLabel,
          headLabel,
        ]),
        { waitUntil: "load" },
      );
      await page.locator("#card").screenshot({ path: join(changesDir, file) });
      lines.push(changeLine(group, ` · [crop](changes/${file})`));
    }
    sections.push(surfaceSection(base, head, lines, computedOnly));
    counts.push(
      `| \`${head.title}\` | ${visible.length} | ${computedOnly.length} |`,
    );
    visibleTotal += visible.length;
    computedOnlyTotal += computedOnly.length;
  }
  await browser.close();

  const changed = sections.length;
  writeFileSync(
    join(outDir, "changes.md"),
    [
      `# Style changes: ${baseLabel} → ${headLabel}`,
      "",
      `${compared} surfaces compared · ${changed} with element-level changes · ${visibleTotal} visible, ${computedOnlyTotal} computed-only. Elements with text are matched by tag and identical text under the same anchor, textless ones by structural path; position shifts alone are ignored. A change is visible when its element's base and head screenshot crops differ in size or in more than 0.5% (and at least 20) of their pixels.`,
      "",
      ...(changed
        ? [
            "| Surface | Visible | Computed-only |",
            "| --- | --- | --- |",
            ...counts,
            "",
            ...sections,
          ]
        : ["No element-level style changes."]),
    ].join("\n"),
  );
  console.info(
    `style diff: ${compared} surfaces compared, ${changed} with changes (${visibleTotal} visible, ${computedOnlyTotal} computed-only)`,
  );
}

await main();
