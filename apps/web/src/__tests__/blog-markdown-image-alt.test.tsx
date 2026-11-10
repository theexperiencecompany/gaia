// @vitest-environment jsdom
// Regression: every blog image rendered with alt="image", discarding the post's alt text.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownWrapper from "@/features/blog/components/MarkdownWrapper";

describe("blog markdown images", () => {
  it("carry the alt text the post wrote", () => {
    render(
      <MarkdownWrapper content="![Flowchart of tool retrieval](/images/blog/diagram.png)" />,
    );
    expect(screen.getByRole("img").getAttribute("alt")).toBe(
      "Flowchart of tool retrieval",
    );
  });

  it("are decorative when the post wrote no alt text", () => {
    const { container } = render(
      <MarkdownWrapper content="![](/images/blog/diagram.png)" />,
    );
    expect(container.querySelector("img")?.getAttribute("alt")).toBe("");
  });
});
