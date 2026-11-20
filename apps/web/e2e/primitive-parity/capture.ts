import type { Page } from "@playwright/test";

import type { Capture, PartMap } from "./types";

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
      // Everything below runs in the page, so its helpers live inside this callback.
      type Styles = Record<string, string>;
      type Point = { left: number; top: number };
      const BORDER_PROPS = props.filter((p) =>
        /^border-(top|right|bottom|left)-(width|style|color)$/.test(p),
      );
      const out: Record<string, Styles> = {};

      const textNodeOf = (el: Element) =>
        [...el.childNodes].find(
          (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
        );

      const innermostWithText = (root: Element, label: string) => {
        let found: Element | null = null;
        for (const el of root.querySelectorAll("*")) {
          if (el.textContent?.trim() === label) found = el;
        }
        return found;
      };

      const upFrom = (anchor: Element, arg: string): Element[] => {
        const [up, down] = arg.split("|");
        const ancestor = anchor.closest(up);
        if (!ancestor) return [];
        if (!down) return [ancestor];
        const el = ancestor.querySelector(down);
        return el ? [el] : [];
      };

      const resolve = (anchor: Element, selector: string): Element[] => {
        if (selector === "self") return [anchor];
        const [kind, ...rest] = selector.split(":");
        const arg = rest.join(":");
        const one = (el: Element | null) => (el ? [el] : []);
        if (kind === "css") return one(anchor.querySelector(arg));
        if (kind === "all") return [...anchor.querySelectorAll(arg)];
        if (kind === "text") return one(innermostWithText(anchor, arg));
        if (kind === "up") return upFrom(anchor, arg);
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

      /** v2 drew a checkbox's outline on its ::before and an underlined field's focus line on a 2px ::after. */
      const readPseudoBorders = (el: Element, part: string, styles: Styles) => {
        const before = getComputedStyle(el, "::before");
        const after = getComputedStyle(el, "::after");
        const filled =
          after.content !== "none" &&
          Number(after.opacity) > 0 &&
          !/, 0\)$|transparent/.test(after.backgroundColor);
        const underline =
          part === "box" &&
          filled &&
          Number.parseFloat(after.height) <= 2 &&
          Number.parseFloat(after.width) > 0 &&
          after.scale !== "0" &&
          styles["border-bottom-width"] === "0px";
        if (underline) {
          styles["border-bottom-width"] = after.height;
          styles["border-bottom-style"] = "solid";
          styles["border-bottom-color"] = after.backgroundColor;
        }
        const outlined =
          styles["border-top-width"] === "0px" &&
          !filled &&
          before.content !== "none" &&
          Number.parseFloat(before.borderTopWidth) > 0;
        if (outlined) {
          for (const prop of BORDER_PROPS)
            styles[prop] = before.getPropertyValue(prop);
        }
      };

      /** Type only shows where the element draws text or a currentColor icon; gap only between two flowing children. */
      const dropUndrawn = (
        el: Element,
        style: CSSStyleDeclaration,
        styles: Styles,
      ) => {
        const drawsIcon =
          el.tagName === "svg" ||
          [...el.children].some((c) => c.tagName === "svg");
        if (!drawsText(el)) {
          for (const prop of TYPE_PROPS) styles[prop] = "n/a";
          if (!drawsIcon) styles.color = "n/a";
        }
        const flowChildren = [...el.children].filter(
          (child) =>
            !["absolute", "fixed"].includes(getComputedStyle(child).position),
        );
        if (!/flex|grid/.test(style.display) || flowChildren.length < 2) {
          styles["row-gap"] = "n/a";
          styles["column-gap"] = "n/a";
        }
      };

      const drawsText = (el: Element) =>
        ["INPUT", "TEXTAREA"].includes(el.tagName) || Boolean(textNodeOf(el));

      /** A radius past half the box draws a pill, whatever the number (v2 wrote 3.4e7px, v3 9999px). */
      const capRadii = (rect: DOMRect, styles: Styles) => {
        const cap = Math.min(rect.width, rect.height) / 2;
        for (const corner of RADII) {
          if (Number.parseFloat(styles[corner]) > cap)
            styles[corner] = `${cap}px`;
        }
      };

      /** The fade a hover or press shows: the duration on background-color (or all). */
      const fadeDuration = (style: CSSStyleDeclaration) => {
        const names = style.transitionProperty.split(",").map((p) => p.trim());
        const durations = style.transitionDuration
          .split(",")
          .map((d) => d.trim());
        const fade = names.findIndex(
          (p) => p === "background-color" || p === "all",
        );
        return fade === -1 ? "0s" : durations[fade % durations.length];
      };

      /** Where the text starts: its first glyph box, or an input's content box (a single line centred in it). */
      const textStart = (
        el: Element,
        style: CSSStyleDeclaration,
        rect: DOMRect,
      ): Point | null => {
        if (!["INPUT", "TEXTAREA"].includes(el.tagName)) {
          const node = textNodeOf(el);
          if (!node) return null;
          const range = document.createRange();
          range.selectNodeContents(node);
          return range.getBoundingClientRect();
        }
        const px = (p: string) => Number.parseFloat(style.getPropertyValue(p));
        const contentTop =
          rect.top + px("border-top-width") + px("padding-top");
        const contentBottom =
          rect.bottom - px("border-bottom-width") - px("padding-bottom");
        return {
          left: rect.left + px("border-left-width") + px("padding-left"),
          top:
            el.tagName === "TEXTAREA"
              ? contentTop
              : (contentTop + contentBottom) / 2,
        };
      };

      /** A scaled element draws its type at the scaled size (v2's floating label: 14px at 85%). */
      const scaleType = (
        el: Element,
        style: CSSStyleDeclaration,
        styles: Styles,
      ) => {
        const scale =
          (style.transform === "none" ? 1 : new DOMMatrix(style.transform).a) *
          (style.scale === "none" ? 1 : Number.parseFloat(style.scale));
        if (!drawsText(el) || scale === 1) return;
        for (const prop of ["font-size", "line-height"]) {
          const value = Number.parseFloat(styles[prop]);
          if (!Number.isNaN(value)) styles[prop] = `${value * scale}px`;
        }
      };

      /** The opacity it shows at, its own times every ancestor's; an invisible part paints no colour or shadow. */
      const applyOpacity = (
        el: Element,
        style: CSSStyleDeclaration,
        styles: Styles,
      ) => {
        let opacity = 1;
        for (let node: Element | null = el; node; node = node.parentElement) {
          opacity *= Number(getComputedStyle(node).opacity);
        }
        styles.opacity = `${Math.round(opacity * 100) / 100}`;
        if (opacity !== 0 && style.visibility !== "hidden") return;
        for (const prop of Object.keys(styles)) {
          if (/color|shadow/.test(prop)) styles[prop] = "n/a";
        }
      };

      /** Layout size, not the bounding box: a spinning v3 spinner's box swells as it turns. */
      const applySize = (
        el: Element,
        rect: DOMRect,
        origin: DOMRect,
        styles: Styles,
      ) => {
        const sized = el instanceof HTMLElement && !el.closest("svg");
        const width = sized
          ? Math.min(el.offsetWidth, rect.width || el.offsetWidth)
          : rect.width;
        const height = sized
          ? Math.min(el.offsetHeight, rect.height || el.offsetHeight)
          : rect.height;
        styles.width = `${width}px`;
        styles.height = `${height}px`;
        styles["offset-x"] = `${rect.left - origin.left}px`;
        styles["offset-y"] = `${rect.top - origin.top}px`;
      };

      /** Where an overlay opens: its box's distance from, and centre against, the trigger it opened from. */
      const applyTriggerGap = (id: string, rect: DOMRect, styles: Styles) => {
        const trigger = document.querySelector(`[data-parity-trigger="${id}"]`);
        if (!trigger) return;
        const t = trigger.getBoundingClientRect();
        const gap = Math.max(
          t.top - rect.bottom,
          rect.top - t.bottom,
          t.left - rect.right,
          rect.left - t.right,
        );
        styles["trigger-gap"] = `${gap}px`;
        styles["trigger-center"] =
          `${rect.left + rect.width / 2 - (t.left + t.width / 2)}px`;
      };

      const readPart = (
        el: Element,
        part: string,
        rect: DOMRect,
        origin: DOMRect,
      ): Styles => {
        const style = getComputedStyle(el);
        const styles: Styles = {};
        for (const prop of props) styles[prop] = style.getPropertyValue(prop);
        readPseudoBorders(el, part, styles);
        dropUndrawn(el, style, styles);
        capRadii(rect, styles);
        styles["transition-duration"] = fadeDuration(style);
        scaleType(el, style, styles);
        applyOpacity(el, style, styles);
        applySize(el, rect, origin, styles);
        const text = textStart(el, style, rect);
        if (text) {
          styles["text-x"] = `${text.left - origin.left}px`;
          styles["text-y"] = `${text.top - origin.top}px`;
        }
        return styles;
      };

      const readAnchor = (anchor: Element, id: string, map: PartMap) => {
        let origin: DOMRect | null = null;
        for (const [name, selector] of Object.entries(map)) {
          const els = resolve(anchor, selector);
          if (els.length === 0)
            out[`${id}::${name}::${state}`] = { missing: "true" };
          els.forEach((el, index) => {
            const part = selector.startsWith("all:") ? `${name}${index}` : name;
            // what shows: v2 slid a progress fill under its track's clip
            const rect =
              anchorAttr === "data-parity"
                ? clipped(el, anchor)
                : el.getBoundingClientRect();
            const first = origin === null;
            origin ??= rect;
            const styles = readPart(el, name, rect, origin);
            if (first) applyTriggerGap(id, rect, styles);
            out[`${id}::${part}::${state}`] = styles;
          });
        }
      };

      for (const anchor of document.querySelectorAll(`[${anchorAttr}]`)) {
        const id = anchor.getAttribute(anchorAttr) ?? "";
        const map = parts[id.split("/")[0]];
        if (map && (!only || id === only)) readAnchor(anchor, id, map);
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
