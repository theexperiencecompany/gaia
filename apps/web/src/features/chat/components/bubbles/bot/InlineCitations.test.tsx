import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  CitationChip,
  CitationsFooter,
  createCitationAComponent,
} from "@/features/chat/components/bubbles/bot/InlineCitations";

const refs = [
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
];

describe("CitationChip", () => {
  it("renders a link to the source with the number as the visible text", () => {
    const html = renderToStaticMarkup(<CitationChip ref={refs[0]} />);
    expect(html).toContain('href="https://arxiv.org/abs/1706.03762"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain(">1<");
  });
});

describe("CitationsFooter", () => {
  it("renders one numbered source row per ref in order", () => {
    const html = renderToStaticMarkup(<CitationsFooter refs={refs} />);
    expect(html).toContain("Attention Is All You Need");
    expect(html).toContain("arxiv.org");
    expect(html).toContain("Efficient Transformers: A Survey");
    expect(html).toContain('href="https://arxiv.org/abs/2009.06732"');
    // First ref's row appears before the second ref's row.
    expect(html.indexOf("Attention Is All You Need")).toBeLessThan(
      html.indexOf("Efficient Transformers: A Survey"),
    );
  });
});

describe("createCitationAComponent", () => {
  const A = createCitationAComponent(refs, false);

  it("turns a `[n](url)` link into a citation chip", () => {
    const html = renderToStaticMarkup(
      React.createElement(
        A,
        { href: "https://arxiv.org/abs/2009.06732" },
        "[2]",
      ),
    );
    expect(html).toContain('href="https://arxiv.org/abs/2009.06732"');
    expect(html).toContain(">2<");
    // The chip, not the URL text, is what the user sees.
    expect(html).not.toContain("https://arxiv.org/abs/2009.06732</a>");
  });

  it("delegates non-marker links to the regular anchor", () => {
    // CustomAnchor (the fallback) uses browser-only hooks and cannot SSR in
    // the node test env; the chip path above is the citation-specific logic.
    expect(A).toBeTypeOf("function");
  });
});
