// @vitest-environment jsdom
/**
 * The page resolves its link during SSR, which sees neither the viewer's
 * session nor their browser, so the open is counted from the browser itself.
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const recordShortLinkOpen = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock("@/features/short-links/api/shortLinksApi", () => ({
  recordShortLinkOpen,
}));

import { LinkOpenBeacon } from "@/features/short-links/components/LinkOpenBeacon";

describe("LinkOpenBeacon", () => {
  it("reports the open once the page is showing in a browser", () => {
    const { rerender } = render(<LinkOpenBeacon slug="abcdefghijk" />);
    rerender(<LinkOpenBeacon slug="abcdefghijk" />);

    expect(recordShortLinkOpen).toHaveBeenCalledOnce();
    expect(recordShortLinkOpen).toHaveBeenCalledWith("abcdefghijk");
  });
});
