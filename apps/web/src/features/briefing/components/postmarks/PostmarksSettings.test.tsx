// @vitest-environment jsdom
import type { PostmarksResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/typed";
import { PostmarksSettings } from "./PostmarksSettings";

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn() },
}));

// maplibre needs WebGL, which jsdom has none of; the globe is driven in the browser.
vi.mock("./PostmarksGlobe", () => ({
  PostmarksGlobe: () => null,
}));

const TOKYO = {
  city_slug: "tokyo",
  city: "Tokyo",
  country: "Japan",
  lat: 35.68,
  lng: 139.69,
  stamp_url: "https://cdn.example/tokyo.webp",
  date: "2026-09-01",
  briefing_id: "brief_tokyo",
} satisfies PostmarksResponse["postmarks"][number];

function renderPostmarks(collection: PostmarksResponse) {
  vi.mocked(api.get).mockResolvedValue(collection);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PostmarksSettings />
    </QueryClientProvider>,
  );
}

describe("PostmarksSettings", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("reads the collection from the postmarks endpoint", async () => {
    renderPostmarks({ total: 85, postmarks: [] });

    await screen.findByText("No stamps yet");
    expect(api.get).toHaveBeenCalledWith("/api/v1/briefings/postmarks", {
      silent: true,
    });
  });

  it("shows one tile for the whole album and says why when no stamp has arrived", async () => {
    renderPostmarks({ total: 85, postmarks: [] });

    expect(await screen.findByText("No stamps yet")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    const album = screen.getByRole("list", { name: "Stamp collection" });
    expect(within(album).getAllByRole("listitem")).toHaveLength(1);
    expect(album.textContent).toContain("85 cities to collect");
    expect(screen.getByText("of 85").textContent).toBe("0 of 85");
  });

  it("files each stamp before a single tile for the cities still to come", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });

    const stamp = await screen.findByRole("link", { name: "Tokyo, Japan" });
    expect(stamp.getAttribute("href")).toBe("/brief/brief_tokyo");
    const album = screen.getByRole("list", { name: "Stamp collection" });
    const items = within(album).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[1].textContent).toContain("84 more cities");
    expect(screen.queryByText("No stamps yet")).toBeNull();
    expect(screen.getByText("of 85").textContent).toBe("1 of 85");
  });

  it("drops the to-come tile once every city is collected", async () => {
    renderPostmarks({ total: 1, postmarks: [TOKYO] });

    await screen.findByRole("link", { name: "Tokyo, Japan" });
    const album = screen.getByRole("list", { name: "Stamp collection" });
    expect(within(album).getAllByRole("listitem")).toHaveLength(1);
  });

  it("captions each stamp with its city on phones, where there is no hover", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });

    const stamp = await screen.findByRole("link", { name: "Tokyo, Japan" });
    const caption = within(stamp).getByText("Tokyo");
    expect(caption.className).toContain("sm:hidden");
  });

  it("names the city, country and arrival date in the stamp's tooltip", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });
    const stamp = await screen.findByRole("link", { name: "Tokyo, Japan" });

    // react-aria opens a tooltip on keyboard focus without the hover delay.
    await act(async () => {
      fireEvent.keyDown(document.body, { key: "Tab" });
      stamp.focus();
    });

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain("Tokyo");
    expect(tooltip.textContent).toContain("Japan");
    expect(tooltip.textContent).toContain("September 1, 2026");
    // Below the stamp, so it never covers the "Collection" heading above the album.
    expect(
      tooltip.closest("[data-placement]")?.getAttribute("data-placement"),
    ).toBe("bottom");
  });
});
