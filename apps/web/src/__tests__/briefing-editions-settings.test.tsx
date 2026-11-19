// @vitest-environment jsdom
/**
 * The editions grid saves each choice as the whole map, keeps one edition on,
 * and never keeps a choice the server refused.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getBriefingEditions = vi.fn();
const updateBriefingEditions = vi.fn();
const toastError = vi.fn();
const toastInfo = vi.fn();

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingEditions: () => getBriefingEditions(),
    updateBriefingEditions: (update: unknown) => updateBriefingEditions(update),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    error: (message: string) => toastError(message),
    info: (message: string) => toastInfo(message),
  },
}));

import { useBriefingEditionsSettings } from "@/features/settings/hooks/useBriefingEditionsSettings";

const STORED = {
  editions: [
    { family: "postal", name: "Air Mail", choice: "on" },
    { family: "swiss", name: "Swiss", choice: "favourite" },
    { family: "menu", name: "Menu", choice: "off" },
  ],
};

async function loaded() {
  const hook = renderHook(() => useBriefingEditionsSettings());
  await waitFor(() => expect(hook.result.current.editions).not.toBeNull());
  return hook;
}

describe("useBriefingEditionsSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getBriefingEditions.mockResolvedValue(STORED);
    updateBriefingEditions.mockResolvedValue(STORED);
  });

  it("takes an edition out of the rotation and saves every choice", async () => {
    const { result } = await loaded();

    act(() => result.current.toggleOn("postal"));

    await waitFor(() =>
      expect(updateBriefingEditions).toHaveBeenCalledWith({
        choices: { postal: "off", swiss: "favourite", menu: "off" },
      }),
    );
    expect(result.current.editions?.[0].choice).toBe("off");
  });

  it("favouriting an edition that is off turns it back on as a favourite", async () => {
    const { result } = await loaded();

    act(() => result.current.toggleFavourite("menu"));

    await waitFor(() =>
      expect(updateBriefingEditions).toHaveBeenCalledWith({
        choices: { postal: "on", swiss: "favourite", menu: "favourite" },
      }),
    );
  });

  it("keeps the last edition on without asking the server", async () => {
    getBriefingEditions.mockResolvedValue({
      editions: [
        { family: "postal", name: "Air Mail", choice: "on" },
        { family: "menu", name: "Menu", choice: "off" },
      ],
    });
    const { result } = await loaded();

    act(() => result.current.toggleOn("postal"));

    expect(toastInfo).toHaveBeenCalledWith("Keep at least one edition on.");
    expect(updateBriefingEditions).not.toHaveBeenCalled();
    expect(result.current.editions?.[0].choice).toBe("on");
  });

  // Regression: two quick taps sent two whole maps at once, and the older one landing last erased the newer choice.
  it("saves quick choices one after another, so the last write holds them all", async () => {
    let finishFirst: ((value: typeof STORED) => void) | undefined;
    updateBriefingEditions.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    );
    const { result } = await loaded();

    act(() => result.current.toggleOn("postal"));
    act(() => result.current.toggleFavourite("menu"));

    await waitFor(() =>
      expect(updateBriefingEditions).toHaveBeenCalledTimes(1),
    );
    await act(async () => finishFirst?.(STORED));

    await waitFor(() =>
      expect(updateBriefingEditions).toHaveBeenCalledTimes(2),
    );
    expect(updateBriefingEditions).toHaveBeenLastCalledWith({
      choices: { postal: "off", swiss: "favourite", menu: "favourite" },
    });
  });

  it("rolls back a choice the server refused", async () => {
    updateBriefingEditions.mockRejectedValue(new Error("500"));
    const { result } = await loaded();

    act(() => result.current.toggleOn("postal"));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Couldn't save your editions."),
    );
    expect(result.current.editions?.[0].choice).toBe("on");
  });
});
