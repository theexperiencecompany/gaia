import { describe, expect, it } from "vitest";
import {
  applyCitationLinks,
  citationRefsFromWebResults,
} from "@/features/chat/utils/citationUtils";

const refs = citationRefsFromWebResults([
  {
    title: "Attention Is All You Need",
    url: "https://arxiv.org/abs/1706.03762",
    content: "",
    score: 0.9,
  },
  {
    title: "Efficient Transformers: A Survey",
    url: "https://arxiv.org/abs/2009.06732",
    content: "",
    score: 0.8,
  },
  {
    title: "Duplicate",
    url: "https://arxiv.org/abs/1706.03762",
    content: "",
    score: 0.7,
  },
]);

describe("citationRefsFromWebResults", () => {
  it("builds numbered refs with label, host, and url", () => {
    expect(refs).toEqual([
      {
        n: 1,
        label: "Attention Is All You Need",
        host: "arxiv.org",
        url: "https://arxiv.org/abs/1706.03762",
      },
      {
        n: 2,
        label: "Efficient Transformers: A Survey",
        host: "arxiv.org",
        url: "https://arxiv.org/abs/2009.06732",
      },
    ]);
  });

  it("dedupes by url and keeps the first occurrence's position", () => {
    expect(refs.map((r) => r.n)).toEqual([1, 2]);
  });

  it("handles missing web results", () => {
    expect(citationRefsFromWebResults(undefined)).toEqual([]);
    expect(citationRefsFromWebResults([])).toEqual([]);
  });

  it("falls back to the url for an empty title and ignores malformed urls", () => {
    const [unnamed, malformed] = citationRefsFromWebResults([
      { title: "", url: "https://example.com/doc", content: "", score: 0.5 },
      { title: "Bad", url: "not-a-url", content: "", score: 0.5 },
    ]);
    expect(unnamed.label).toBe("https://example.com/doc");
    expect(unnamed.host).toBe("example.com");
    expect(malformed.host).toBe("");
  });
});

describe("applyCitationLinks", () => {
  it("passes text through untouched when there are no refs", () => {
    expect(applyCitationLinks("see [1] here", []).text).toBe("see [1] here");
  });

  it("turns resolved markers into source links", () => {
    const { text, used } = applyCitationLinks(
      "transformers scale well[1], though attention is quadratic[2]",
      refs,
    );
    expect(text).toBe(
      "transformers scale well[1](https://arxiv.org/abs/1706.03762), though attention is quadratic[2](https://arxiv.org/abs/2009.06732)",
    );
    expect(used.map((r) => r.n)).toEqual([1, 2]);
  });

  it("reports used refs in first-appearance order", () => {
    const { used } = applyCitationLinks(
      "second[2] then first[1] again[2]",
      refs,
    );
    expect(used.map((r) => r.n)).toEqual([2, 1]);
  });

  it("leaves unresolvable markers literal", () => {
    const { text, used } = applyCitationLinks("out of range[9]", refs);
    expect(text).toBe("out of range[9]");
    expect(used).toEqual([]);
  });

  it("leaves a marker adjacent to another marker literal", () => {
    const { text } = applyCitationLinks("see[1][2]", refs);
    expect(text).toBe("see[1](https://arxiv.org/abs/1706.03762)[2]");
  });

  it("does not double-link an already-linked marker", () => {
    const already = "[1](https://example.com/other)";
    expect(applyCitationLinks(already, refs).text).toBe(already);
  });

  it("handles multi-digit markers", () => {
    const ten = citationRefsFromWebResults(
      Array.from({ length: 10 }, (_, i) => ({
        title: `R${i + 1}`,
        url: `https://example.com/${i + 1}`,
        content: "",
        score: 0.5,
      })),
    );
    const { text } = applyCitationLinks("see[10]", ten);
    expect(text).toBe("see[10](https://example.com/10)");
  });

  it("never touches markers inside fenced code blocks", () => {
    const content =
      "answer here[1]\n\n```python\nx = a[1] + b[2]\n```\n\nafter[2]";
    const { text } = applyCitationLinks(content, refs);
    expect(text).toContain("answer here[1](https://arxiv.org/abs/1706.03762)");
    expect(text).toContain("```python\nx = a[1] + b[2]\n```");
    expect(text).toContain("after[2](https://arxiv.org/abs/2009.06732)");
  });

  it("never touches markers inside inline code", () => {
    const { text } = applyCitationLinks("use `arr[1]` here[2]", refs);
    expect(text).toContain("use `arr[1]` here");
    expect(text).toContain("here[2](https://arxiv.org/abs/2009.06732)");
  });

  it("leaves a partially streamed marker literal", () => {
    const { text } = applyCitationLinks("see[", refs);
    expect(text).toBe("see[");
  });
});
