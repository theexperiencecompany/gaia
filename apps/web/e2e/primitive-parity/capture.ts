import type { Page } from "@playwright/test";

/**
 * Where a part sits relative to its anchor (the data-parity cell, or an open
 * overlay's data-parity-mark): "self", "css:<selector>" inside it, "all:<selector>"
 * (one part per match, suffixed with its index), "text:<label>" (the innermost
 * element whose text is the label), "up:<selector>" (the closest ancestor) and
 * "up:<selector>|<selector>" (a descendant of that ancestor).
 */
export type PartSelector = string;
export type PartMap = Record<string, PartSelector>;
export type Styles = Record<string, string>;
/** `<id>::<part>::<state>` to the part's computed styles in that state. */
export type Capture = Record<string, Styles>;

export const STYLE_PROPS = [
  "border-top-width",
  "border-right-width",
  "border-bottom-width",
  "border-left-width",
  "border-top-style",
  "border-right-style",
  "border-bottom-style",
  "border-left-style",
  "border-top-color",
  "border-right-color",
  "border-bottom-color",
  "border-left-color",
  "outline-width",
  "outline-style",
  "outline-color",
  "outline-offset",
  "box-shadow",
  "border-top-left-radius",
  "border-top-right-radius",
  "border-bottom-right-radius",
  "border-bottom-left-radius",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "row-gap",
  "column-gap",
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
  "color",
  "background-color",
  "opacity",
  "transition-duration",
] as const;

const RADII = [
  "border-top-left-radius",
  "border-top-right-radius",
  "border-bottom-right-radius",
  "border-bottom-left-radius",
] as const;

export const TYPE_PROPS = [
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
] as const;

/** Reads every part's computed styles, plus its size and its offset from the first part, in the page. */
export function captureParts(
  page: Page,
  anchorAttr: "data-parity" | "data-parity-mark",
  parts: Record<string, PartMap>,
  state: string,
  only?: string,
): Promise<Capture> {
  return page.evaluate(
    ({ anchorAttr, parts, state, only, props, TYPE_PROPS, RADII }) => {
      const out: Record<string, Record<string, string>> = {};
      const innermostWithText = (root: Element, label: string) => {
        let found: Element | null = null;
        for (const el of root.querySelectorAll("*")) {
          if (el.textContent?.trim() === label) found = el;
        }
        return found;
      };
      const resolve = (anchor: Element, selector: string): Element[] => {
        if (selector === "self") return [anchor];
        const [kind, ...rest] = selector.split(":");
        const arg = rest.join(":");
        if (kind === "css") {
          const el = anchor.querySelector(arg);
          return el ? [el] : [];
        }
        if (kind === "all") return [...anchor.querySelectorAll(arg)];
        if (kind === "text") {
          const el = innermostWithText(anchor, arg);
          return el ? [el] : [];
        }
        if (kind === "up") {
          const [up, down] = arg.split("|");
          const ancestor = anchor.closest(up);
          if (!ancestor) return [];
          if (!down) return [ancestor];
          const el = ancestor.querySelector(down);
          return el ? [el] : [];
        }
        throw new Error(`unknown part selector ${selector}`);
      };
      // clipped to the overflow-hiding ancestors inside the fixture cell (an overlay is never clipped)
      const clipped = (el: Element, cell: Element) => {
        const box = el.getBoundingClientRect();
        let [left, top, right, bottom] = [
          box.left,
          box.top,
          box.right,
          box.bottom,
        ];
        for (
          let node = el.parentElement;
          node && node !== cell;
          node = node.parentElement
        ) {
          const style = getComputedStyle(node);
          const clip = node.getBoundingClientRect();
          // per axis: the page's body clips only sideways (overflow-x: clip)
          if (style.overflowX !== "visible") {
            left = Math.max(left, clip.left);
            right = Math.min(right, clip.right);
          }
          if (style.overflowY !== "visible") {
            top = Math.max(top, clip.top);
            bottom = Math.min(bottom, clip.bottom);
          }
        }
        return new DOMRect(
          left,
          top,
          Math.max(0, right - left),
          Math.max(0, bottom - top),
        );
      };
      for (const anchor of document.querySelectorAll(`[${anchorAttr}]`)) {
        const id = anchor.getAttribute(anchorAttr) ?? "";
        if (only && id !== only) continue;
        const kind = id.split("/")[0];
        const map = parts[kind];
        if (!map) continue;
        let origin: DOMRect | null = null;
        for (const [name, selector] of Object.entries(map)) {
          const els = resolve(anchor, selector);
          els.forEach((el, index) => {
            const part = selector.startsWith("all:") ? `${name}${index}` : name;
            const style = getComputedStyle(el);
            // what shows: v2 slid a progress fill under its track's clip
            const rect =
              anchorAttr === "data-parity"
                ? clipped(el, anchor)
                : el.getBoundingClientRect();
            origin ??= rect;
            const styles: Record<string, string> = {};
            for (const prop of props)
              styles[prop] = style.getPropertyValue(prop);
            // v2 drew a checkbox's outline on its ::before, not the control itself
            const before = getComputedStyle(el, "::before");
            const after = getComputedStyle(el, "::after");
            const filled =
              after.content !== "none" &&
              Number(after.opacity) > 0 &&
              !/, 0\)$|transparent/.test(after.backgroundColor);
            // and its underlined field's focus line on a 2px ::after along the bottom
            if (
              name === "box" &&
              filled &&
              Number.parseFloat(after.height) <= 2 &&
              Number.parseFloat(after.width) > 0 &&
              after.scale !== "0" &&
              styles["border-bottom-width"] === "0px"
            ) {
              styles["border-bottom-width"] = after.height;
              styles["border-bottom-style"] = "solid";
              styles["border-bottom-color"] = after.backgroundColor;
            }
            if (
              styles["border-top-width"] === "0px" &&
              !filled &&
              before.content !== "none" &&
              Number.parseFloat(before.borderTopWidth) > 0
            ) {
              for (const prop of props.filter((p) =>
                /^border-(top|right|bottom|left)-(width|style|color)$/.test(p),
              )) {
                styles[prop] = before.getPropertyValue(prop);
              }
            }
            // type only shows where the element draws text or a currentColor icon
            const drawsText =
              ["INPUT", "TEXTAREA"].includes(el.tagName) ||
              [...el.childNodes].some(
                (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
              );
            const drawsIcon =
              el.tagName === "svg" ||
              [...el.children].some((c) => c.tagName === "svg");
            if (!drawsText) {
              for (const prop of TYPE_PROPS) styles[prop] = "n/a";
              if (!drawsIcon) styles.color = "n/a";
            }
            // gap only spaces the children of a flex or grid box with two or more
            const flowChildren = [...el.children].filter(
              (child) =>
                !["absolute", "fixed"].includes(
                  getComputedStyle(child).position,
                ),
            );
            if (!/flex|grid/.test(style.display) || flowChildren.length < 2) {
              styles["row-gap"] = "n/a";
              styles["column-gap"] = "n/a";
            }
            // a radius past half the box draws a pill, whatever the number (v2 wrote 3.4e7px, v3 9999px)
            for (const corner of RADII) {
              const radius = Number.parseFloat(styles[corner]);
              const cap = Math.min(rect.width, rect.height) / 2;
              if (radius > cap) styles[corner] = `${cap}px`;
            }
            // the fade a hover or press shows: the duration on background-color (or all)
            const names = style.transitionProperty
              .split(",")
              .map((p) => p.trim());
            const durations = style.transitionDuration
              .split(",")
              .map((d) => d.trim());
            const fade = names.findIndex(
              (p) => p === "background-color" || p === "all",
            );
            styles["transition-duration"] =
              fade === -1 ? "0s" : durations[fade % durations.length];
            // where the text starts: its first glyph box, or an input's content box
            let textRect: { left: number; top: number } | null = null;
            if (["INPUT", "TEXTAREA"].includes(el.tagName)) {
              const px = (p: string) =>
                Number.parseFloat(style.getPropertyValue(p));
              textRect = {
                left: rect.left + px("border-left-width") + px("padding-left"),
                top:
                  el.tagName === "TEXTAREA"
                    ? rect.top + px("border-top-width") + px("padding-top")
                    : // a single-line input centres its text in its content box
                      (rect.top +
                        px("border-top-width") +
                        px("padding-top") +
                        rect.bottom -
                        px("border-bottom-width") -
                        px("padding-bottom")) /
                      2,
              };
            } else {
              const node = [...el.childNodes].find(
                (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
              );
              if (node) {
                const range = document.createRange();
                range.selectNodeContents(node);
                textRect = range.getBoundingClientRect();
              }
            }
            // a scaled element draws its type at the scaled size (v2's floating label: 14px at 85%)
            const scale =
              (style.transform === "none"
                ? 1
                : new DOMMatrix(style.transform).a) *
              (style.scale === "none" ? 1 : Number.parseFloat(style.scale));
            if (drawsText && scale !== 1) {
              for (const prop of ["font-size", "line-height"]) {
                const value = Number.parseFloat(styles[prop]);
                if (!Number.isNaN(value)) styles[prop] = `${value * scale}px`;
              }
            }
            // the opacity it shows at: its own times every ancestor's
            let opacity = 1;
            for (
              let node: Element | null = el;
              node;
              node = node.parentElement
            ) {
              opacity *= Number(getComputedStyle(node).opacity);
            }
            styles.opacity = `${Math.round(opacity * 100) / 100}`;
            // an invisible part paints nothing: its colours and shadow cannot differ
            if (opacity === 0 || style.visibility === "hidden") {
              for (const prop of Object.keys(styles)) {
                if (/color|shadow/.test(prop)) styles[prop] = "n/a";
              }
            }
            // layout size, not the bounding box: a spinning v3 spinner's box swells as it turns
            const sized = el instanceof HTMLElement && !el.closest("svg");
            styles.width = `${sized ? Math.min(el.offsetWidth, rect.width || el.offsetWidth) : rect.width}px`;
            styles.height = `${sized ? Math.min(el.offsetHeight, rect.height || el.offsetHeight) : rect.height}px`;
            styles["offset-x"] = `${rect.left - origin.left}px`;
            styles["offset-y"] = `${rect.top - origin.top}px`;
            // where an overlay opens: its box's distance from the trigger it opened from
            const trigger = document.querySelector(
              `[data-parity-trigger="${id}"]`,
            );
            if (trigger && index === 0 && name === Object.keys(map)[0]) {
              const t = trigger.getBoundingClientRect();
              styles["trigger-gap"] =
                `${Math.max(t.top - rect.bottom, rect.top - t.bottom, t.left - rect.right, rect.left - t.right)}px`;
              styles["trigger-center"] =
                `${rect.left + rect.width / 2 - (t.left + t.width / 2)}px`;
            }
            if (textRect && origin) {
              styles["text-x"] = `${textRect.left - origin.left}px`;
              styles["text-y"] = `${textRect.top - origin.top}px`;
            }
            out[`${id}::${part}::${state}`] = styles;
          });
          if (els.length === 0)
            out[`${id}::${name}::${state}`] = { missing: "true" };
        }
      }
      return out;
    },
    {
      anchorAttr,
      parts,
      state,
      only,
      props: [...STYLE_PROPS],
      TYPE_PROPS: [...TYPE_PROPS],
      RADII: [...RADII],
    },
  );
}
