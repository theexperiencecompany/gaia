// @vitest-environment jsdom
/**
 * Quiet hours load the stored window, save each change, and never store an
 * empty window or keep a change the server refused.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getQuietHours = vi.fn();
const updateQuietHours = vi.fn();
const toastError = vi.fn();

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getQuietHours: () => getQuietHours(),
    updateQuietHours: (window: unknown) => updateQuietHours(window),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: (message: string) => toastError(message), success: vi.fn() },
}));

import { useQuietHoursSettings } from "@/features/settings/hooks/useQuietHoursSettings";

async function loaded() {
  const hook = renderHook(() => useQuietHoursSettings());
  await waitFor(() => expect(hook.result.current.quietHours).not.toBeNull());
  return hook;
}

describe("useQuietHoursSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getQuietHours.mockResolvedValue({ start_hour: 22, end_hour: 8 });
    updateQuietHours.mockImplementation((window: unknown) =>
      Promise.resolve(window),
    );
  });

  it("saves a moved edge and shows what the server stored", async () => {
    const { result } = await loaded();

    await act(() => result.current.setEdge("start_hour", 23));

    expect(updateQuietHours).toHaveBeenCalledWith({
      start_hour: 23,
      end_hour: 8,
    });
    expect(result.current.quietHours).toEqual({ start_hour: 23, end_hour: 8 });
  });

  it("refuses an empty window without calling the server", async () => {
    const { result } = await loaded();

    await act(() => result.current.setEdge("start_hour", 8));

    expect(updateQuietHours).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
    expect(result.current.quietHours).toEqual({ start_hour: 22, end_hour: 8 });
  });

  it("says the load failed instead of leaving the window unknown", async () => {
    getQuietHours.mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useQuietHoursSettings());

    await waitFor(() => expect(result.current.loadFailed).toBe(true));
    expect(result.current.quietHours).toBeNull();
  });

  it("rolls back a change the server refused", async () => {
    updateQuietHours.mockRejectedValue(new Error("down"));
    const { result } = await loaded();

    await act(() => result.current.setEdge("end_hour", 7));

    expect(result.current.quietHours).toEqual({ start_hour: 22, end_hour: 8 });
    expect(toastError).toHaveBeenCalledWith("Couldn't save your quiet hours.");
  });
});
