// @vitest-environment jsdom
import type { Postmark } from "@shared/api/generated";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderWithQueryClient } from "@/__tests__/helpers/queryClient";
import { PostmarksGlobe } from "./PostmarksGlobe";

// maplibre needs WebGL, which jsdom has none of: the globe's chrome renders as plain children.
vi.mock("@/components/ui/map", () => ({
  MapView: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  MapMarker: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  MarkerContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  MarkerTooltip: () => null,
  MapArc: () => null,
}));
vi.mock("../../hooks/useGlobeSpin", () => ({ useGlobeSpin: vi.fn() }));
vi.mock("../../hooks/useNightGlobeBasemap", () => ({
  useNightGlobeBasemap: vi.fn(),
}));

const { fetchBriefing } = vi.hoisted(() => ({
  fetchBriefing: vi.fn(() => new Promise(() => undefined)),
}));
vi.mock("@/lib/api/typed", () => ({
  api: { get: () => fetchBriefing() },
}));

const TOKYO: Postmark = {
  city_slug: "tokyo",
  city: "Tokyo",
  country: "Japan",
  lat: 35.68,
  lng: 139.69,
  stamp_url: "https://cdn.example/tokyo.webp",
  date: "2026-09-01",
  briefing_id: "brief_tokyo",
  edition: null,
};

describe("PostmarksGlobe", () => {
  it("makes each city light a button a keyboard can reach and press", async () => {
    renderWithQueryClient(<PostmarksGlobe postmarks={[TOKYO]} />);

    const light = screen.getByRole("button", { name: "Tokyo, Japan" });
    light.focus();
    expect(document.activeElement).toBe(light);

    fireEvent.click(light);
    await waitFor(() => expect(fetchBriefing).toHaveBeenCalled());
  });
});
