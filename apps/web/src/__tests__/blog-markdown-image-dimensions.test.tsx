// @vitest-environment jsdom
// Regression: blog images must carry their local file's intrinsic width/height —
// including when the src is a Cloudflare Image Resizing URL — so the browser can
// reserve the right box before the image loads.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownWrapper from "@/features/blog/components/MarkdownWrapper";

const DIAGRAM =
  "/images/blog/how-tool-calling-works/Untitled_diagram-2025-11-11-183214.png";

describe("blog markdown image dimensions", () => {
  it("uses the intrinsic size of a local blog image", () => {
    render(<MarkdownWrapper content={`![Architecture diagram](${DIAGRAM})`} />);
    const image = screen.getByRole("img");

    expect(image.getAttribute("width")).toBe("2490");
    expect(image.getAttribute("height")).toBe("1960");
  });

  it("resolves a CDN-transformed URL back to the source file's size", () => {
    render(
      <MarkdownWrapper
        content={`![Architecture diagram](/cdn-cgi/image/width=3840,quality=75,format=auto${DIAGRAM})`}
      />,
    );
    const image = screen.getByRole("img");

    expect(image.getAttribute("width")).toBe("2490");
    expect(image.getAttribute("height")).toBe("1960");
  });
});
