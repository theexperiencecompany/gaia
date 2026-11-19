// @vitest-environment jsdom
import type {
  BriefingEditions,
  BriefingEditionsUpdate,
} from "@shared/api/generated";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  renderWithQueryClient,
  testQueryClient,
} from "@/__tests__/helpers/queryClient";
import { useBriefingEditionsSettings } from "@/features/settings/hooks/useBriefingEditionsSettings";
import { toast } from "@/lib/toast";
import { BriefingEditionsSettings } from "./BriefingEditionsSettings";

const { getEditions, updateEditions } = vi.hoisted(() => ({
  getEditions: vi.fn(),
  updateEditions: vi.fn(),
}));
vi.mock("@/lib/api/typed", () => ({
  api: {
    get: () => getEditions(),
    put: (_path: string, init: { body: BriefingEditionsUpdate }) =>
      updateEditions(init.body),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn() },
}));

const STORED: BriefingEditions = {
  editions: [
    { family: "postal", name: "Air Mail", choice: "on" },
    { family: "swiss", name: "Swiss", choice: "favourite" },
    { family: "menu", name: "Menu", choice: "off" },
  ],
};

/** The edition's Disabled chip, whether it shows or only holds its place. */
function chipOf(name: string): HTMLElement | null {
  const row = screen.getByText(name).parentElement;
  return row ? within(row).queryByText("Disabled") : null;
}

async function loadedHook() {
  const client = testQueryClient();
  const hook = renderHook(() => useBriefingEditionsSettings(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  await waitFor(() => expect(hook.result.current.editions).not.toBeNull());
  return hook;
}

describe("BriefingEditionsSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getEditions.mockResolvedValue(STORED);
    updateEditions.mockResolvedValue(STORED);
  });

  it("marks only the editions taken out of the rotation as Disabled", async () => {
    renderWithQueryClient(<BriefingEditionsSettings />);

    await screen.findByText("Menu");
    expect(chipOf("Menu")?.closest("[aria-hidden]")).toBeNull();
    expect(chipOf("Air Mail")?.closest("[aria-hidden]")).toBeTruthy();
    expect(chipOf("Swiss")?.closest("[aria-hidden]")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Menu: off, tap to turn on" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("holds the Disabled chip's place on every edition, so turning one off shifts nothing", async () => {
    renderWithQueryClient(<BriefingEditionsSettings />);

    await screen.findByText("Menu");
    for (const name of ["Air Mail", "Swiss", "Menu"]) {
      expect(chipOf(name)).toBeTruthy();
    }
    expect(chipOf("Swiss")?.closest(".invisible")).toBeTruthy();
    expect(chipOf("Menu")?.closest(".invisible")).toBeNull();
  });

  it("opens an edition full screen on its sample brief without changing its choice", async () => {
    renderWithQueryClient(<BriefingEditionsSettings />);

    fireEvent.click(
      await screen.findByRole("button", { name: "See Swiss full screen" }),
    );

    const dialog = await screen.findByRole("dialog");
    const demo = within(dialog).getByAltText(
      "Swiss edition drawing a sample brief",
    );
    expect(demo.getAttribute("src")).toContain(
      encodeURIComponent("/images/briefing/editions/demo/swiss.webp"),
    );
    expect(updateEditions).not.toHaveBeenCalled();
  });

  it("offers a retry when the editions could not be read", async () => {
    getEditions
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue(STORED);
    renderWithQueryClient(<BriefingEditionsSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Menu")).toBeTruthy();
  });

  describe("choices", () => {
    it("takes an edition out of the rotation and saves every choice", async () => {
      const { result } = await loadedHook();

      act(() => result.current.toggleOn("postal"));

      await waitFor(() =>
        expect(updateEditions).toHaveBeenCalledWith({
          choices: { postal: "off", swiss: "favourite", menu: "off" },
        }),
      );
      expect(result.current.editions?.[0].choice).toBe("off");
    });

    it("favouriting an edition that is off turns it back on as a favourite", async () => {
      const { result } = await loadedHook();

      act(() => result.current.toggleFavourite("menu"));

      await waitFor(() =>
        expect(updateEditions).toHaveBeenCalledWith({
          choices: { postal: "on", swiss: "favourite", menu: "favourite" },
        }),
      );
    });

    it("keeps the last edition on without asking the server", async () => {
      getEditions.mockResolvedValue({
        editions: [
          { family: "postal", name: "Air Mail", choice: "on" },
          { family: "menu", name: "Menu", choice: "off" },
        ],
      });
      const { result } = await loadedHook();

      act(() => result.current.toggleOn("postal"));

      expect(toast.info).toHaveBeenCalledWith("Keep at least one edition on.");
      expect(updateEditions).not.toHaveBeenCalled();
      expect(result.current.editions?.[0].choice).toBe("on");
    });

    // Regression: two quick taps sent two whole maps at once, and the older one landing last erased the newer choice.
    it("saves quick choices one after another, so the last write holds them all", async () => {
      let finishFirst: ((value: BriefingEditions) => void) | undefined;
      updateEditions.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = resolve;
          }),
      );
      const { result } = await loadedHook();

      act(() => result.current.toggleOn("postal"));
      act(() => result.current.toggleFavourite("menu"));

      await waitFor(() => expect(updateEditions).toHaveBeenCalledTimes(1));
      await act(async () => finishFirst?.(STORED));

      await waitFor(() => expect(updateEditions).toHaveBeenCalledTimes(2));
      expect(updateEditions).toHaveBeenLastCalledWith({
        choices: { postal: "off", swiss: "favourite", menu: "favourite" },
      });
    });

    it("rolls back a choice the server refused", async () => {
      updateEditions.mockRejectedValue(new Error("500"));
      const { result } = await loadedHook();

      act(() => result.current.toggleOn("postal"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Couldn't save your editions.",
        ),
      );
      expect(result.current.editions?.[0].choice).toBe("on");
    });
  });
});
