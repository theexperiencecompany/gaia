import { assert, describe, expect, it } from "vitest";
import {
  parseBlocks,
  parseInline,
  repairStreamingMarkdown,
} from "./markdown-parser";

describe("parseInline — one segment per construct", () => {
  it("parses links", () => {
    const segs = parseInline("see [docs](https://example.com) now");
    expect(segs).toEqual([
      { type: "text", text: "see " },
      { type: "link", text: "docs", url: "https://example.com" },
      { type: "text", text: " now" },
    ]);
  });

  it("parses images with alt and url", () => {
    const segs = parseInline("![a photo](https://example.com/pic.png)");
    expect(segs).toEqual([
      { type: "image", alt: "a photo", url: "https://example.com/pic.png" },
    ]);
  });

  it("parses bold, italic and bold-italic distinctly", () => {
    expect(parseInline("**bold**")).toEqual([{ type: "bold", text: "bold" }]);
    expect(parseInline("*ital*")).toEqual([{ type: "italic", text: "ital" }]);
    expect(parseInline("***both***")).toEqual([
      { type: "boldItalic", text: "both" },
    ]);
  });

  it("parses strikethrough, inline code and math as distinct types", () => {
    expect(parseInline("~~gone~~")).toEqual([
      { type: "strikethrough", text: "gone" },
    ]);
    expect(parseInline("`x = 1`")).toEqual([{ type: "code", text: "x = 1" }]);
    expect(parseInline("$E=mc^2$")).toEqual([
      { type: "mathInline", text: "E=mc^2" },
    ]);
  });

  it("decodes HTML entities in plain text", () => {
    expect(parseInline("a &amp; b &lt;c&gt;")).toEqual([
      { type: "text", text: "a & b <c>" },
    ]);
  });
});

describe("parseBlocks", () => {
  it("parses a GFM table with alignment", () => {
    const blocks = parseBlocks(["| a | b |", "| --- | :---: |", "| 1 | 2 |"]);
    expect(blocks).toHaveLength(1);
    const table = blocks[0];
    assert(table.type === "table");
    expect(table.rows).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
    expect(table.alignments).toEqual([null, "center"]);
  });

  it("parses nested lists recursively", () => {
    const blocks = parseBlocks(["- item1", "  - nested A", "- item2"]);
    expect(blocks).toHaveLength(1);
    const list = blocks[0];
    assert(list.type === "list");
    expect(list.items).toHaveLength(2);
    const [first] = list.items;
    // First item renders its text plus the recursively-parsed sublist.
    expect(first.blocks.map((b) => b.type)).toEqual(["paragraph", "list"]);
    const nested = first.blocks[1];
    assert(nested.type === "list");
    expect(nested.items).toHaveLength(1);
  });

  it("preserves the starting number of ordered lists", () => {
    const blocks = parseBlocks(["3. three", "4. four"]);
    const list = blocks[0];
    assert(list.type === "list");
    expect(list.start).toBe(3);
  });

  it("preserves single newlines inside a paragraph", () => {
    const blocks = parseBlocks(["line one", "line two"]);
    const para = blocks[0];
    assert(para.type === "paragraph");
    expect(para.segments[0]).toEqual({
      type: "text",
      text: "line one\nline two",
    });
  });

  it("parses task list items", () => {
    const blocks = parseBlocks(["- [x] done", "- [ ] todo"]);
    const list = blocks[0];
    assert(list.type === "list");
    expect(list.items.map((i) => [i.task, i.checked])).toEqual([
      [true, true],
      [true, false],
    ]);
  });
});

describe("parseBlocks — termination guarantees", () => {
  it("does not stall on a delimiter line with no table header", () => {
    // Regression: a lone table-delimiter line is a block boundary that no
    // parser accepts; parseBlocks must advance past it, not loop forever.
    expect(() =>
      parseBlocks(["| --- | --- |", "hello"]).map((b) => b.type),
    ).not.toThrow();
    const blocks = parseBlocks(["| --- | --- |", "hello"]);
    expect(blocks.some((b) => b.type === "paragraph")).toBe(true);
  });

  it("does not stall on a lone delimiter line", () => {
    expect(parseBlocks(["| --- | --- |"])).toEqual([]);
  });
});

describe("repairStreamingMarkdown", () => {
  it("closes an unclosed code fence opened at line start", () => {
    const md = "Here is code:\n```js\nconst x = 1;";
    const repaired = repairStreamingMarkdown(md);
    const blocks = parseBlocks(repaired.split("\n"));
    expect(blocks.some((b) => b.type === "codeBlock")).toBe(true);
  });

  it("does not alter complete markdown", () => {
    const md = "# Title\n\ndone **bold** `code`\n";
    expect(repairStreamingMarkdown(md)).toBe(md);
  });
});
