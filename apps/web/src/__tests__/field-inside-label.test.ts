import { readFileSync } from "node:fs";
import path from "node:path";
import postcss, { Rule } from "postcss";
import { describe, expect, it } from "vitest";

import { fieldVariants } from "@/components/shared/fieldVariants";

const GAIA_CSS = readFileSync(
  path.resolve(__dirname, "../app/styles/gaia.css"),
  "utf8",
);
const VISIBLE_LABEL_GATE = ".gaia-field-inside:has(> .label:not(.sr-only))";

/** Every selector in gaia.css that styles the inside-label layout. */
function insideLabelSelectors(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...withoutComments.matchAll(/([^{}]+)\{/g)]
    .flatMap(([, selectorList]) => selectorList.split(","))
    .map((selector) => selector.trim())
    .filter((selector) => /\.gaia-field-inside\b/.test(selector));
}

// v2's useLabelPlacement fell back to an outside (40px) field when no label
// rendered; an aria-label or sr-only label must keep the plain field.
describe("inside-label fields", () => {
  it("lay out inside only when a visible Label renders", () => {
    const selectors = insideLabelSelectors(GAIA_CSS);
    expect(selectors.length).toBeGreaterThan(0);
    expect(
      selectors.filter((selector) => !selector.startsWith(VISIBLE_LABEL_GATE)),
    ).toEqual([]);
  });

  // An InputGroup.Prefix centred on the 56px field sat above the value, which
  // sits under the label (MCPIntegrationModal's icons); v2 put it on the value's row.
  it("puts a prefix and suffix on the value's row", () => {
    const valueRow = new Set<string>();
    postcss.parse(GAIA_CSS).walkDecls("padding-top", (decl) => {
      if (decl.value !== "var(--gaia-field-inside-padding-top)") return;
      if (!(decl.parent instanceof Rule)) return;
      for (const selector of decl.parent.selectors)
        valueRow.add(selector.split(/\s+/).at(-1) ?? "");
    });
    expect([...valueRow]).toEqual(
      expect.arrayContaining([
        ".input-group__input",
        ".input-group__prefix",
        ".input-group__suffix",
      ]),
    );
  });

  // v2's sm inside field (the email edit modal) was 48px with the value 20px
  // down; inputVariants' sm alone pinned it to a 32px outside field.
  it("takes v2's sm geometry when combined with inputVariants sm", () => {
    const smTokens = new Map<string, string>();
    postcss.parse(GAIA_CSS).walkRules((rule) => {
      if (!rule.selectors.includes(`${VISIBLE_LABEL_GATE}.gaia-input-sm`))
        return;
      rule.walkDecls((decl) => {
        smTokens.set(decl.prop, decl.value);
      });
    });
    expect(smTokens.get("--gaia-field-inside-height")).toBe(
      "var(--gaia-field-inside-sm-height)",
    );
    expect(smTokens.get("--gaia-field-inside-padding-top")).toBe(
      "var(--gaia-field-inside-sm-padding-top)",
    );
  });

  it("is opted into through fieldVariants alone", () => {
    expect(fieldVariants({ labelPlacement: "inside" })).toBe(
      "gaia-field-inside",
    );
    expect(fieldVariants()).toBeFalsy();
  });
});
