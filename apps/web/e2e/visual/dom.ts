import type { Page } from "@playwright/test";

/** Which capture phase of a visual-diff run a snapshot belongs to. */
export type Side = "base" | "head";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One visible element: its structural key, document-relative box and the styles the diff compares. */
export interface DomElement {
  /** `body>div:1>p:2`, one `tag:nth-of-type` per level. */
  path: string;
  /** Own text (first 40 chars), else aria-label or alt; empty when it has none. */
  label: string;
  /** The id and role attributes when set; snapshots from before they were recorded lack them. */
  id?: string;
  role?: string;
  rect: Rect;
  styles: Record<string, string>;
}

export interface DomSnapshot {
  id: string;
  title: string;
  side: Side;
  truncated: boolean;
  elements: DomElement[];
}

export const STYLE_PROPERTIES = [
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
  "color",
  "background-color",
  "background-image",
  ...["top", "right", "bottom", "left"].flatMap((side) =>
    ["width", "style", "color"].map((part) => `border-${side}-${part}`),
  ),
  "border-top-left-radius",
  "border-top-right-radius",
  "border-bottom-right-radius",
  "border-bottom-left-radius",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "margin-top",
  "margin-right",
  "margin-bottom",
  "margin-left",
  "gap",
  "box-shadow",
  "outline-style",
  "outline-width",
  "opacity",
  "animation-name",
] as const;

const MAX_ELEMENTS = 4000;
const LABEL_CHARS = 40;

/** Snapshot every visible element of the settled page, in document order. */
export async function captureDom(
  page: Page,
  meta: { id: string; title: string; side: Side },
): Promise<DomSnapshot> {
  const { elements, truncated } = await page.evaluate(
    ({ properties, maxElements, labelChars }) => {
      const skipped = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
      const paths = new Map<Element, string>([[document.body, "body"]]);
      const pathOf = (element: Element): string => {
        const known = paths.get(element);
        if (known) return known;
        const parent = element.parentElement ?? document.body;
        let index = 1;
        for (
          let sibling = element.previousElementSibling;
          sibling;
          sibling = sibling.previousElementSibling
        ) {
          if (sibling.tagName === element.tagName) index += 1;
        }
        const path = `${pathOf(parent)}>${element.tagName.toLowerCase()}:${index}`;
        paths.set(element, path);
        return path;
      };
      const labelOf = (element: Element): string => {
        const ownText = [...element.childNodes]
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent ?? "")
          .join(" ")
          .replace(/\s+/g, " ")
          .trim();
        const label =
          ownText ||
          element.getAttribute("aria-label") ||
          element.getAttribute("alt") ||
          "";
        return label.slice(0, labelChars);
      };
      const pageWidth = document.documentElement.scrollWidth;
      const pageHeight = document.documentElement.scrollHeight;
      const found: DomElement[] = [];
      for (const element of document.body.querySelectorAll("*")) {
        if (skipped.has(element.tagName)) continue;
        const box = element.getBoundingClientRect();
        if (box.width === 0 || box.height === 0) continue;
        const rect = {
          x: Math.round(box.left + window.scrollX),
          y: Math.round(box.top + window.scrollY),
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
        const inPage =
          rect.x + rect.width > 0 &&
          rect.y + rect.height > 0 &&
          rect.x < pageWidth &&
          rect.y < pageHeight;
        const computed = getComputedStyle(element);
        if (!inPage || computed.visibility === "hidden") continue;
        if (found.length === maxElements)
          return { elements: found, truncated: true };
        const styles: Record<string, string> = {};
        for (const property of properties) {
          styles[property] = computed.getPropertyValue(property);
        }
        styles["background-image"] =
          styles["background-image"] === "none" ? "none" : "set";
        const role = element.getAttribute("role");
        found.push({
          path: pathOf(element),
          label: labelOf(element),
          ...(element.id && { id: element.id }),
          ...(role && { role }),
          rect,
          styles,
        });
      }
      return { elements: found, truncated: false };
    },
    {
      properties: [...STYLE_PROPERTIES],
      maxElements: MAX_ELEMENTS,
      labelChars: LABEL_CHARS,
    },
  );
  return { ...meta, truncated, elements };
}
