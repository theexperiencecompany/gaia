// @vitest-environment jsdom
/**
 * The /brief/[id] page: the rendered edition stands alone (no second text copy
 * of the letter under it), a brief without an edition reads as text with
 * clock times, and the loading and error states keep the GAIA shell.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

vi.mock("@/features/short-links/components/ShareLinkControls", () => ({
  ShareLinkControls: () => null,
}));

const briefingQuery = vi.fn();
vi.mock("@/features/briefing/hooks/useBriefingQuery", () => ({
  useBriefingQuery: (id: string) => briefingQuery(id),
}));

import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "@/features/briefing/components/BriefingEdition";
import { BriefingPage } from "@/features/briefing/components/BriefingPage";

const HEADLINE = "One payment failed overnight";
const MESSAGE = "The Stripe retry runs at noon.";

const PAYLOAD: BriefingEditionPayload = {
  kicker: "THE MORNING BRIEF",
  date: "2026-11-11",
  headline: HEADLINE,
  lede: "",
  stats: [],
  sections: [
    {
      numeral: "I",
      title: "Needs you",
      items: [{ text: "Reply to Dana", kind: "you" }],
    },
  ],
  mood: "packed",
  caption: "",
  hue: 10,
  message: MESSAGE,
  calendar: [{ date: "2026-11-11", start: "13:00", title: "Lunch and learn" }],
};

describe("brief page", () => {
  beforeEach(() => {
    briefingQuery.mockReset();
  });

  it("shows the rendered edition alone, without repeating the letter under it", () => {
    render(
      <BriefingEdition
        payload={PAYLOAD}
        imageUrl="https://cdn.example/edition.png"
      />,
    );

    expect(screen.getByRole("img", { name: HEADLINE })).toBeTruthy();
    expect(screen.queryByText(HEADLINE)).toBeNull();
    expect(screen.queryByText(MESSAGE)).toBeNull();
    expect(screen.queryByText("Reply to Dana")).toBeNull();
    expect(screen.queryByText("Lunch and learn")).toBeNull();
  });

  it("reads a brief without an edition as text, its times on a clock", () => {
    render(<BriefingEdition payload={PAYLOAD} />);

    expect(screen.getByText(HEADLINE)).toBeTruthy();
    expect(screen.getByText("Reply to Dana")).toBeTruthy();
    expect(screen.queryByText("13:00")).toBeNull();
    expect(screen.getByText("1:00 PM")).toBeTruthy();
  });

  it("keeps the GAIA shell and offers a way back when the brief is gone", () => {
    briefingQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });
    render(<BriefingPage briefingId="brief_gone" />);

    expect(
      screen.getByText("This brief isn't available anymore."),
    ).toBeTruthy();
    expect(screen.queryByText(/another account/)).toBeNull();
    expect(screen.getByRole("link", { name: "GAIA home" })).toBeTruthy();
    expect(
      screen
        .getByText("Open your briefings")
        .closest("a")
        ?.getAttribute("href"),
    ).toBe("/briefings");
  });

  it("keeps the GAIA shell while the brief loads", () => {
    briefingQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });
    render(<BriefingPage briefingId="brief_1" />);

    expect(screen.getByRole("link", { name: "GAIA home" })).toBeTruthy();
  });
});
