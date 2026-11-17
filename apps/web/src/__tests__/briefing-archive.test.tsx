// @vitest-environment jsdom
/**
 * The briefings archive says when it could not load, offers a retry, groups
 * its folded cards by week with the weekly recap leading, and pages back.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchBriefings = vi.fn();

vi.mock("@/lib/api/typed", () => ({
  api: {
    get: (_path: string, init: { query: { before?: string } }) =>
      fetchBriefings(init.query.before ?? null),
  },
}));

import { BriefingArchive } from "@/features/briefing";

function renderArchive(children: ReactNode = <BriefingArchive />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

const brief = {
  id: "brief_1",
  user_id: "u1",
  date: "2026-10-14",
  kind: "daily",
  delivered_channels: ["inapp"],
  edition_image_url: null,
  opened_at: null,
  created_at: "2026-10-14T02:30:00Z",
  updated_at: null,
  edition_name: "Air Mail",
  stamp_city_name: "Bogotá",
  needs_you_count: 1,
  payload: {
    kicker: "THE MORNING BRIEF",
    date: "2026-10-14",
    headline: "Your morning, sorted",
    lede: "",
    caption: "",
    mood: "packed",
    stats: [],
    calendar: [],
    sections: [
      {
        numeral: "I",
        title: "GAIA's work",
        items: [{ text: "Investor update", kind: "lookback", todo_id: null }],
      },
    ],
  },
};

describe("BriefingArchive", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says it could not load and retries on request", {
    timeout: 15000,
  }, async () => {
    // The hook retries twice on its own before the archive gives up.
    fetchBriefings
      .mockRejectedValueOnce(new Error("500"))
      .mockRejectedValueOnce(new Error("500"))
      .mockRejectedValueOnce(new Error("500"))
      .mockResolvedValueOnce({ briefings: [brief], next_cursor: null });

    renderArchive();

    expect(
      await screen.findByText(
        "Couldn't load your briefings.",
        {},
        { timeout: 8000 },
      ),
    ).toBeTruthy();
    expect(screen.queryByText("No past briefings yet.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(screen.getByText("Your morning, sorted")).toBeTruthy(),
    );
  });

  it("groups briefs by week, leads with the weekly recap and titles each card alone", async () => {
    const weekly = {
      ...brief,
      id: "brief_w",
      kind: "weekly",
      date: "2026-10-18",
      edition_name: "The Week",
      stamp_city_name: null,
      needs_you_count: 4,
      payload: {
        ...brief.payload,
        headline: "A steady week",
        lede: "Five briefs, two launches.",
      },
    };
    const lastWeek = { ...brief, id: "brief_old", date: "2026-10-07" };
    fetchBriefings.mockResolvedValueOnce({
      briefings: [brief, weekly, lastWeek],
      next_cursor: null,
    });

    renderArchive();

    const cards = await screen.findAllByRole("button", {
      name: /^Open brief:/,
    });
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Open brief: A steady week",
      "Open brief: Your morning, sorted",
      "Open brief: Your morning, sorted",
    ]);
    expect(screen.getByText("Oct 12 – Oct 18")).toBeTruthy();
    expect(screen.getByText("Oct 5 – Oct 11")).toBeTruthy();
    expect(screen.getByText("Weekly")).toBeTruthy();
    expect(screen.getAllByText("Daily")).toHaveLength(2);
    expect(screen.getByText("The Week")).toBeTruthy();
    expect(screen.queryByText("Weekly recap")).toBeNull();
    expect(screen.getAllByText("Air Mail, Bogotá")).toHaveLength(2);
    expect(screen.queryByText("Five briefs, two launches.")).toBeNull();
    expect(screen.queryByText(/waiting/)).toBeNull();
    expect(screen.queryByText(/\d+ briefs?$/)).toBeNull();
  });

  it("reads the next page from where the last one ended, until there is none", async () => {
    const lastWeek = {
      ...brief,
      id: "brief_old",
      date: "2026-10-07",
      payload: { ...brief.payload, headline: "An older morning" },
    };
    fetchBriefings
      .mockResolvedValueOnce({ briefings: [brief], next_cursor: "brief_1" })
      .mockResolvedValueOnce({ briefings: [lastWeek], next_cursor: null });

    renderArchive();

    fireEvent.click(
      await screen.findByRole("button", { name: "Show older briefs" }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Open brief: An older morning",
      }),
    ).toBeTruthy();
    expect(fetchBriefings.mock.calls).toEqual([[null], ["brief_1"]]);
    expect(
      screen.getByRole("button", { name: "Open brief: Your morning, sorted" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Show older briefs" }),
    ).toBeNull();
  });
});
