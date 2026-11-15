// @vitest-environment jsdom
import type { BriefingEdition } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
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

describe("BriefingEditionsSettings", () => {
  it("marks only the editions taken out of the rotation as Disabled", async () => {
    vi.mocked(NotificationsAPI.getBriefingEditions).mockResolvedValue({
      editions: EDITIONS,
    });
    render(<BriefingEditionsSettings />);

    const disabled = await screen.findAllByText("Disabled");
    expect(disabled).toHaveLength(1);
    expect(screen.getByText("GAIA Band").parentElement?.textContent).toBe(
      "GAIA BandDisabled",
    );
    expect(
      screen
        .getByRole("button", { name: "GAIA Band: off, tap to turn on" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });
});
