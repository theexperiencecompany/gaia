// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchHours = vi.fn();
const updateHours = vi.fn();

vi.mock("@/features/settings/api/quietHoursApi", () => ({
  quietHoursApi: {
    fetch: () => fetchHours(),
    update: (...args: unknown[]) => updateHours(...args),
  },
}));

vi.mock("@/lib/timezone", () => ({
  getUserHomeTimezone: () => "Asia/Kolkata",
}));

import { QuietHoursSettings } from "@/features/settings/components/QuietHoursSettings";
import {
  formatHour,
  fromAxis,
  toAxis,
} from "@/features/settings/utils/quietHoursAxis";

const NIGHT = { enabled: true, start_hour: 22, end_hour: 8 };

describe("the quiet-hours axis", () => {
  it.each([
    [{ start_hour: 22, end_hour: 8 }, [22, 32]],
    [{ start_hour: 0, end_hour: 6 }, [24, 30]],
    [{ start_hour: 13, end_hour: 15 }, [13, 15]],
    [{ start_hour: 20, end_hour: 12 }, [20, 36]],
    [{ start_hour: 12, end_hour: 18 }, [12, 18]],
  ])("places %o on the noon-to-noon axis as %o", (hours, axis) => {
    expect(toAxis(hours)).toEqual(axis);
    expect(fromAxis(axis as [number, number])).toEqual(hours);
  });

  it("writes hours the way the locale does", () => {
    expect(formatHour(22, "en-US")).toBe("10 PM");
    expect(formatHour(32, "en-US")).toBe("8 AM");
    expect(formatHour(22, "en-GB")).toBe("22");
  });
});

describe("the quiet-hours section", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchHours.mockResolvedValue(NIGHT);
    updateHours.mockImplementation(async (hours) => hours);
  });

  it("shows the stored window, its length and the timezone", async () => {
    render(<QuietHoursSettings />);

    expect(
      await screen.findByText(`${formatHour(22)} to ${formatHour(8)}`),
    ).toBeTruthy();
    expect(screen.getByText("10 hours, in Asia/Kolkata")).toBeTruthy();
  });

  it("turns quiet hours off and keeps the window", async () => {
    render(<QuietHoursSettings />);

    fireEvent.click(
      await screen.findByRole("switch", { name: "Use quiet hours" }),
    );

    expect(updateHours).toHaveBeenCalledWith({ ...NIGHT, enabled: false });
    await waitFor(() => expect(screen.getByText("Off")).toBeTruthy());
  });

  it("goes back to the stored window when a save fails", async () => {
    updateHours.mockRejectedValue(new Error("500"));
    render(<QuietHoursSettings />);

    fireEvent.click(
      await screen.findByRole("switch", { name: "Use quiet hours" }),
    );

    await waitFor(() =>
      expect(
        screen.getByText(`${formatHour(22)} to ${formatHour(8)}`),
      ).toBeTruthy(),
    );
  });
});
