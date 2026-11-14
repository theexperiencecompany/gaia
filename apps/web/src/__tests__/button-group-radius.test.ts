// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

const GAIA = path.resolve(__dirname, "../app/styles/gaia.css");
const RADIUS = /^border(-(start|end)-(start|end))?-radius$/;
const ZERO = new Set(["0", "0px"]);

/** The corners a ButtonGroup rule in the gaia layer rounds on `el` (the rules that square it are skipped). */
function cornersOf(el: Element): string[] {
  const out: string[] = [];
  postcss.parse(readFileSync(GAIA, "utf8")).walkRules((rule) => {
    const groupSelectors = rule.selectors.filter((s) =>
      s.startsWith(".button-group"),
    );
    if (!groupSelectors.some((selector) => el.matches(selector))) return;
    rule.walkDecls((decl) => {
      if (RADIUS.test(decl.prop) && !ZERO.has(decl.value)) {
        out.push(decl.prop);
      }
    });
  });
  return out;
}

/** HoloCardEditor's toolbar: each icon button inside its Tooltip.Trigger wrapper. */
function wrappedToolbar(count: number): Element[] {
  document.body.innerHTML = `<div class="button-group button-group--horizontal">${Array.from(
    { length: count },
    () =>
      '<div class="tooltip__trigger"><button class="button button--icon-only"></button></div>',
  ).join("")}</div>`;
  return [...document.querySelectorAll(".button")];
}

// Regression: a Tooltip.Trigger wraps each button in its own div, so HeroUI's
// .button:first-child:last-child matched every button and the toolbar came apart
// into separately rounded buttons instead of v2's one joined pill.
describe("a ButtonGroup of wrapped buttons", () => {
  it("rounds only the outer corners of its end buttons", () => {
    const [first, middle, last] = wrappedToolbar(3);
    expect(cornersOf(middle)).toEqual([]);
    expect(cornersOf(first).sort()).toEqual([
      "border-end-start-radius",
      "border-start-start-radius",
    ]);
    expect(cornersOf(last).sort()).toEqual([
      "border-end-end-radius",
      "border-start-end-radius",
    ]);
  });

  it("rounds a lone wrapped button on every corner", () => {
    const [only] = wrappedToolbar(1);
    expect(cornersOf(only)).toContain("border-radius");
  });
});
