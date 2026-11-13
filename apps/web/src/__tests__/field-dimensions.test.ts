import { readFileSync } from "node:fs";
import path from "node:path";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

const GAIA_CSS = postcss.parse(
  readFileSync(path.resolve(__dirname, "../app/styles/gaia.css"), "utf8"),
);

/** Every value gaia.css gives a property on a selector, across all the rules that list it. */
function valuesFor(selector: string, prop: string): string[] {
  const values: string[] = [];
  GAIA_CSS.walkRules((rule) => {
    if (!rule.selectors.includes(selector)) return;
    rule.walkDecls(prop, (decl) => {
      values.push(decl.value);
    });
  });
  return values;
}

// inputVariants({ size: "sm" }) is v2's 32px field (the workflow schedule row):
// its ComboBox stood 40px tall beside 32px selects, and an unpadded sm Select
// trigger stretched its value to the full row, so the text sat at the top.
describe("the sm field size", () => {
  it("covers a ComboBox row", () => {
    expect(
      valuesFor(".gaia-input-sm .combo-box__input-group", "height"),
    ).toContain("var(--gaia-input-sm-height)");
  });

  it("centres a Select's value on its 32px trigger", () => {
    expect(
      valuesFor(".gaia-input-sm .select__trigger", "align-items"),
    ).toContain("center");
  });
});

// v2's flat Textarea with a transparent wrapper still stood in its 40px field
// row, one line centred; v3's bare textarea dropped to 38px with the text at the
// top, so the workflow modal's description sat jammed under its title.
describe("a bare textarea", () => {
  it("keeps the field's 40px row", () => {
    expect(valuesFor(".textarea.gaia-input-bare", "min-height")).toContain(
      "var(--gaia-field-height)",
    );
  });
});
