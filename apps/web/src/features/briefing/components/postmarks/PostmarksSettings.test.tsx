// @vitest-environment jsdom
import type { PostmarksResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as preparedEditionModule from "@/features/briefing/utils/preparedEdition";
import { prepareEdition } from "@/features/briefing/utils/preparedEdition";
import { api } from "@/lib/api/typed";
import { PostmarksSettings } from "./PostmarksSettings";

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn() },
}));

// jsdom cannot decode an edition; what matters is when the stamp asks for it.
vi.mock(
  "@/features/briefing/utils/preparedEdition",
  async (importOriginal) => ({
    ...(await importOriginal<typeof preparedEditionModule>()),
    prepareEdition: vi.fn(() => new Promise(() => undefined)),
  }),
);

// jsdom lays out no grid; the album is read at a five-column width.
vi.mock("@/features/briefing/hooks/useGridColumnCount", () => ({
  useGridColumnCount: () => [{ current: null }, 5],
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
  edition_image_url: null,
  edition_fold: null,
  edition_paper: null,
} satisfies PostmarksResponse["postmarks"][number];

const LISBON = {
  ...TOKYO,
  city_slug: "lisbon",
  city: "Lisbon",
  country: "Portugal",
  briefing_id: "brief_lisbon",
} satisfies PostmarksResponse["postmarks"][number];

// No edition image, so the brief opens as its text sheet: jsdom cannot decode an edition.
const TOKYO_BRIEF = {
  id: "brief_tokyo",
  user_id: "u1",
  date: "2026-09-01",
  kind: "daily",
  delivered_channels: ["inapp"],
  edition_image_url: null,
  edition_fold: null,
  edition_paper: null,
  opened_at: null,
  created_at: "2026-09-01T02:30:00Z",
  updated_at: null,
  payload: {
    kicker: "THE MORNING BRIEF",
    date: "2026-09-01",
    headline: "A quiet Tuesday from Tokyo",
    lede: "",
    caption: "",
    mood: "calm",
    hue: 10,
    stats: [],
    calendar: [],
    sections: [],
  },
};

/** The album's blank cells, the cities still to collect. */
function blanks(): Element[] {
  return Array.from(
    screen
      .getByRole("list", { name: "Stamp collection" })
      .querySelectorAll("li[aria-hidden]"),
  );
}

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
    vi.mocked(prepareEdition).mockClear();
  });

  it("reads the collection from the postmarks endpoint", async () => {
    renderPostmarks({ total: 85, postmarks: [] });

    await screen.findByText("No stamps yet");
    expect(api.get).toHaveBeenCalledWith("/api/v1/briefings/postmarks", {
      silent: true,
    });
  });

  it("lays one row of blanks when no stamp has arrived, the last counting the rest", async () => {
    renderPostmarks({ total: 85, postmarks: [] });

    expect(await screen.findByText("No stamps yet")).toBeTruthy();
    const album = screen.getByRole("list", { name: "Stamp collection" });
    expect(within(album).queryAllByRole("button")).toHaveLength(0);
    expect(blanks()).toHaveLength(5);
    expect(blanks().at(-1)?.textContent).toBe("+81 more to unlock");
    expect(screen.getByText(/of 85/).textContent).toBe("0 of 85 cities");
  });

  it("shows the collected stamps in full, in arrival order, then blanks only to finish their row", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO, LISBON] });

    await screen.findByRole("button", { name: "Tokyo, Japan" });
    const album = screen.getByRole("list", { name: "Stamp collection" });
    expect(
      within(album)
        .getAllByRole("button")
        .map((stamp) => stamp.getAttribute("aria-label")),
    ).toEqual(["Tokyo, Japan", "Lisbon, Portugal"]);
    expect(blanks()).toHaveLength(3);
    expect(blanks().map((blank) => blank.textContent)).toEqual([
      "",
      "",
      "+81 more to unlock",
    ]);
    expect(screen.queryByText("No stamps yet")).toBeNull();
    expect(screen.getByText(/of 85/).textContent).toBe("2 of 85 cities");
  });

  it("leaves no blank once every city is collected", async () => {
    renderPostmarks({ total: 1, postmarks: [TOKYO] });

    await screen.findByRole("button", { name: "Tokyo, Japan" });
    expect(blanks()).toHaveLength(0);
  });

  it("unfolds the stamp's brief in place, with a way to its full page", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });
    vi.mocked(api.get).mockResolvedValueOnce(TOKYO_BRIEF);

    fireEvent.click(
      await screen.findByRole("button", { name: "Tokyo, Japan" }),
    );

    const fullBrief = await screen.findByText("Open full brief");
    expect(fullBrief.closest("a")?.getAttribute("href")).toBe(
      "/brief/brief_tokyo",
    );
    expect(screen.getByText(TOKYO_BRIEF.payload.headline)).toBeTruthy();
    expect(api.get).toHaveBeenLastCalledWith(
      "/api/v1/briefings/{briefing_id}",
      {
        path: { briefing_id: "brief_tokyo" },
        silent: true,
      },
    );
  });

  it("readies the stamp's edition when the pointer reaches it, without opening the brief", async () => {
    const edition = "https://cdn.example/tokyo-edition.png";
    renderPostmarks({
      total: 85,
      postmarks: [{ ...TOKYO, edition_image_url: edition, edition_fold: 0.3 }],
    });
    const stamp = await screen.findByRole("button", { name: "Tokyo, Japan" });
    expect(prepareEdition).not.toHaveBeenCalled();

    fireEvent.pointerEnter(stamp);

    expect(prepareEdition).toHaveBeenCalledWith(edition, {
      fold: 0.3,
      paper: null,
    });
    // Fetching the brief is what marks it opened, so hovering must not.
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("captions each stamp with its city on phones, where there is no hover", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });

    const stamp = await screen.findByRole("button", { name: "Tokyo, Japan" });
    const caption = within(stamp).getByText("Tokyo");
    expect(caption.className).toContain("sm:hidden");
  });

  it("names the city, country and arrival date in the stamp's tooltip", async () => {
    renderPostmarks({ total: 85, postmarks: [TOKYO] });
    const stamp = await screen.findByRole("button", { name: "Tokyo, Japan" });

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
