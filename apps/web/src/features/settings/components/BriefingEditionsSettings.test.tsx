// @vitest-environment jsdom
import type { BriefingEdition } from "@shared/api/generated";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationsAPI } from "@/services/api/notifications";
import { BriefingEditionsSettings } from "./BriefingEditionsSettings";

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingEditions: vi.fn(),
    updateBriefingEditions: vi.fn(),
  },
}));

const EDITIONS: BriefingEdition[] = [
  { family: "airmail", name: "Air Mail", choice: "favourite" },
  { family: "band", name: "GAIA Band", choice: "off" },
  { family: "almanac", name: "The Almanac", choice: "on" },
];

/** The edition's Disabled chip, whether it shows or only holds its place. */
function chipOf(name: string): HTMLElement | null {
  const row = screen.getByText(name).parentElement;
  return row ? within(row).queryByText("Disabled") : null;
}

describe("BriefingEditionsSettings", () => {
  it("marks only the editions taken out of the rotation as Disabled", async () => {
    vi.mocked(NotificationsAPI.getBriefingEditions).mockResolvedValue({
      editions: EDITIONS,
    });
    render(<BriefingEditionsSettings />);

    await screen.findByText("GAIA Band");
    expect(chipOf("GAIA Band")?.closest("[aria-hidden]")).toBeNull();
    expect(chipOf("Air Mail")?.closest("[aria-hidden]")).toBeTruthy();
    expect(chipOf("The Almanac")?.closest("[aria-hidden]")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "GAIA Band: off, tap to turn on" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("holds the Disabled chip's place on every edition, so turning one off shifts nothing", async () => {
    vi.mocked(NotificationsAPI.getBriefingEditions).mockResolvedValue({
      editions: EDITIONS,
    });
    render(<BriefingEditionsSettings />);

    await screen.findByText("GAIA Band");
    for (const name of ["Air Mail", "GAIA Band", "The Almanac"]) {
      expect(chipOf(name)).toBeTruthy();
    }
    expect(chipOf("The Almanac")?.closest(".invisible")).toBeTruthy();
    expect(chipOf("GAIA Band")?.closest(".invisible")).toBeNull();
  });

  it("opens an edition full screen on its sample brief without changing its choice", async () => {
    vi.mocked(NotificationsAPI.getBriefingEditions).mockResolvedValue({
      editions: EDITIONS,
    });
    render(<BriefingEditionsSettings />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "See The Almanac full screen",
      }),
    );

    const dialog = await screen.findByRole("dialog");
    const demo = within(dialog).getByAltText(
      "The Almanac edition drawing a sample brief",
    );
    expect(demo.getAttribute("src")).toContain(
      encodeURIComponent("/images/briefing/editions/demo/almanac.webp"),
    );
    expect(NotificationsAPI.updateBriefingEditions).not.toHaveBeenCalled();
  });
});
