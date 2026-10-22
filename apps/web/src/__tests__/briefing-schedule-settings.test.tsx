// @vitest-environment jsdom
/**
 * The briefing schedule loads what is stored, saves each change, and never
 * keeps a change the server refused.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getBriefingSchedule = vi.fn();
const updateBriefingSchedule = vi.fn();
const toastError = vi.fn();

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingSchedule: () => getBriefingSchedule(),
    updateBriefingSchedule: (schedule: unknown) =>
      updateBriefingSchedule(schedule),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: (message: string) => toastError(message), success: vi.fn() },
}));

import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";

async function loaded() {
  const hook = renderHook(() => useBriefingScheduleSettings());
  await waitFor(() => expect(hook.result.current.schedule).not.toBeNull());
  return hook;
}

describe("useBriefingScheduleSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getBriefingSchedule.mockResolvedValue({ frequency: "daily", hour: 8 });
    updateBriefingSchedule.mockImplementation((schedule: unknown) =>
      Promise.resolve(schedule),
    );
  });

  it("saves a new frequency with the hour already set", async () => {
    const { result } = await loaded();

    await act(() => result.current.update({ frequency: "weekdays" }));

    expect(updateBriefingSchedule).toHaveBeenCalledWith({
      frequency: "weekdays",
      hour: 8,
    });
    expect(result.current.schedule).toEqual({ frequency: "weekdays", hour: 8 });
  });

  it("does not call the server when nothing changed", async () => {
    const { result } = await loaded();

    await act(() => result.current.update({ hour: 8 }));

    expect(updateBriefingSchedule).not.toHaveBeenCalled();
  });

  it("rolls back a change the server refused", async () => {
    updateBriefingSchedule.mockRejectedValue(new Error("500"));
    const { result } = await loaded();

    await act(() => result.current.update({ frequency: "off" }));

    expect(result.current.schedule).toEqual({ frequency: "daily", hour: 8 });
    expect(toastError).toHaveBeenCalled();
  });
});
