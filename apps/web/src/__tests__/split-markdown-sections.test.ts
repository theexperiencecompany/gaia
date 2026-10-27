import { describe, expect, it } from "vitest";

import { rehypeSplitMarkdownSections } from "@/features/blog/utils/splitMarkdownSections";

interface TestNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: TestNode[];
  value?: string;
}

function paragraph(text: string): TestNode {
  return {
    type: "element",
    tagName: "p",
    properties: {},
    children: [{ type: "text", value: text }],
  };
}

function heading(tagName: string, text: string): TestNode {
  return {
    type: "element",
    tagName,
    properties: {},
    children: [{ type: "text", value: text }],
  };
}

function split(children: TestNode[]): TestNode[] {
  const tree = { type: "root", children };
  (rehypeSplitMarkdownSections() as (tree: unknown) => void)(tree);
  return tree.children as TestNode[];
}

describe("rehypeSplitMarkdownSections", () => {
  it("leaves content before the first heading at the root", () => {
    const nodes = split([paragraph("intro"), heading("h2", "One")]);

    expect(nodes.map((node) => node.tagName ?? node.type)).toEqual([
      "p",
      "section",
    ]);
    expect(nodes[1]?.children?.map((node) => node.tagName)).toEqual(["h2"]);
  });

  it("starts a section at each h1, h2 and h3 without dropping nodes", () => {
    const content = [
      paragraph("intro"),
      heading("h1", "Title"),
      paragraph("a"),
      heading("h2", "Two"),
      paragraph("b"),
      heading("h3", "Three"),
      paragraph("c"),
    ];

    const nodes = split(content);
    const sections = nodes.filter((node) => node.tagName === "section");

    expect(nodes).toHaveLength(4);
    expect(sections.map((section) => section.children?.length)).toEqual([
      2, 2, 2,
    ]);
    expect(
      sections.flatMap((section) =>
        section.children?.map((node) => node.tagName),
      ),
    ).toEqual(["h1", "p", "h2", "p", "h3", "p"]);
  });
});
