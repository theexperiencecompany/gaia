import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import PageNotFound from "@/app/not-found";
import { NOT_FOUND_LINKS } from "@/lib/not-found-links";

// useRouter is only consumed by the "Go Back" onClick handler; outside the
// Next.js runtime it throws E238 during static rendering.
vi.mock("next/navigation", () => ({ useRouter: () => ({ back: vi.fn() }) }));

describe("PageNotFound static markup", () => {
  it("renders every recovery link as a plain anchor", () => {
    const html = renderToStaticMarkup(<PageNotFound />);
    expect(html).toContain("404");
    expect(html).toContain("Page Not Found");
    for (const { href, name } of NOT_FOUND_LINKS) {
      expect(html).toContain(`href="${href}"`);
      expect(html).toContain(`>${name}<`);
    }
    // Real anchors in the HTML — not JS-only rendering.
    expect((html.match(/<a /g) ?? []).length).toBeGreaterThanOrEqual(
      NOT_FOUND_LINKS.length,
    );
  });
});
