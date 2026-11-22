import type { Root } from "mdast";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { describe, expect, it } from "vitest";

import { remarkBareListMarker } from "./remarkBareListMarker";

function transform(markdown: string): Root {
  const processor = unified().use(remarkParse).use(remarkBareListMarker);
  return processor.runSync(processor.parse(markdown), markdown);
}

describe("remarkBareListMarker", () => {
  it("renders a reply of just a number as text, not an empty list", () => {
    expect(transform("42.").children).toEqual([
      expect.objectContaining({
        type: "paragraph",
        children: [{ type: "text", value: "42." }],
      }),
    ]);
  });

  it("keeps the literal delimiter of a bare marker", () => {
    expect(transform("7)").children[0]).toMatchObject({
      type: "paragraph",
      children: [{ type: "text", value: "7)" }],
    });
  });

  it("leaves a list with content untouched", () => {
    expect(transform("1. Milk\n2. Eggs").children[0]).toMatchObject({
      type: "list",
      ordered: true,
    });
  });

  it("leaves a list with one empty item among filled ones untouched", () => {
    expect(transform("1. Milk\n2.").children[0]).toMatchObject({
      type: "list",
    });
  });
});
