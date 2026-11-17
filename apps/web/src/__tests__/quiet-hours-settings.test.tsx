// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
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

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

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
    render(<QuietHoursSettings />, { wrapper });

    expect(
      await screen.findByText(`${formatHour(22)} to ${formatHour(8)}`),
    ).toBeTruthy();
    expect(screen.getByText("10 hours, in Asia/Kolkata")).toBeTruthy();
  });

  it("turns quiet hours off and keeps the window", async () => {
    render(<QuietHoursSettings />, { wrapper });

    fireEvent.click(
      await screen.findByRole("switch", { name: "Use quiet hours" }),
    );

    await waitFor(() =>
      expect(updateHours).toHaveBeenCalledWith({ ...NIGHT, enabled: false }),
    );
    await waitFor(() => expect(screen.getByText("Off")).toBeTruthy());
  });

  it("sends a second save only after the first lands, and keeps showing the second", async () => {
    const pending: Array<() => void> = [];
    updateHours.mockImplementation(
      (hours) => new Promise((resolve) => pending.push(() => resolve(hours))),
    );
    render(<QuietHoursSettings />, { wrapper });
    const toggle = await screen.findByRole("switch", {
      name: "Use quiet hours",
    });

    fireEvent.click(toggle);
    fireEvent.click(toggle);
    await waitFor(() => expect(updateHours).toHaveBeenCalledTimes(1));
    expect(updateHours).toHaveBeenLastCalledWith({ ...NIGHT, enabled: false });

    pending[0]();
    await waitFor(() => expect(updateHours).toHaveBeenCalledTimes(2));
    expect(updateHours).toHaveBeenLastCalledWith(NIGHT);
    expect(
      screen.getByText(`${formatHour(22)} to ${formatHour(8)}`),
    ).toBeTruthy();

    pending[1]();
    await waitFor(() =>
      expect(
        screen.getByText(`${formatHour(22)} to ${formatHour(8)}`),
      ).toBeTruthy(),
    );
  });

  it("saves the window a thumb was moved to", async () => {
    render(<QuietHoursSettings />, { wrapper });
    const [startThumb] = await screen.findAllByRole("slider");

    fireEvent.keyDown(startThumb, { key: "ArrowRight" });
    fireEvent.keyUp(startThumb, { key: "ArrowRight" });

    await waitFor(() =>
      expect(updateHours).toHaveBeenCalledWith({ ...NIGHT, start_hour: 23 }),
    );
  });

  it("labels the axis at noon and midnight", async () => {
    render(<QuietHoursSettings />, { wrapper });

    expect(await screen.findByText("Midnight")).toBeTruthy();
    expect(screen.getAllByText("Noon")).toHaveLength(2);
  });

  it("shows nothing, and throws nothing, when the stored window cannot be read", async () => {
    fetchHours.mockRejectedValue(new Error("500"));
    const { container } = render(<QuietHoursSettings />, { wrapper });

    await waitFor(() => expect(fetchHours).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.innerHTML).toBe("");
  });

  it("goes back to the stored window when a save fails", async () => {
    updateHours.mockRejectedValue(new Error("500"));
    render(<QuietHoursSettings />, { wrapper });

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
