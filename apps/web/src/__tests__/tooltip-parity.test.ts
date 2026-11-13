import { readFileSync } from "node:fs";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { AtRule } from "postcss";
import { expect, it } from "vitest";

const BASE = path.resolve(__dirname, "../app/styles/base.css");

/** The value an unlayered rule gives a custom property; unlayered beats HeroUI's theme layer. */
async function unlayeredValue(prop: string): Promise<string | undefined> {
  const { root } = await postcss([tailwind()]).process(
    readFileSync(BASE, "utf8"),
    { from: BASE },
  );
  let value: string | undefined;
  root.walkDecls(prop, (decl) => {
    for (let node = decl.parent; node; node = node.parent as typeof node) {
      if (node instanceof AtRule && node.name === "layer") return;
    }
    value = decl.value;
  });
  return value;
}

// HeroUI's Tooltip reads its delays from these tokens; v3's theme opens after
// 1500ms where v2 opened at once, so a hover shorter than that showed nothing.
it("tooltips open and close on v2's timing", async () => {
  expect(await unlayeredValue("--tooltip-delay")).toBe("0ms");
  expect(await unlayeredValue("--tooltip-close-delay")).toBe("500ms");
});

// v3's tooltip body is 12px text in an 8px inset, broken mid-word; v2's was 14px in 4px by 10px, wrapped between words.
it("a tooltip body takes v2's type and inset", async () => {
  expect(await unlayeredValue("--gaia-tooltip-font-size")).toBe("0.875rem");
  const gaia = postcss.parse(
    readFileSync(path.resolve(__dirname, "../app/styles/gaia.css"), "utf8"),
  );
  const tooltipProps = new Set<string>();
  gaia.walkRules(".tooltip", (rule) => {
    rule.walkDecls((decl) => {
      tooltipProps.add(`${decl.prop}: ${decl.value}`);
    });
  });
  expect([...tooltipProps]).toEqual(
    expect.arrayContaining([
      "font-size: var(--gaia-tooltip-font-size)",
      "word-break: normal",
      "padding: var(--gaia-tooltip-padding-y) var(--gaia-tooltip-padding-x)",
    ]),
  );
});
