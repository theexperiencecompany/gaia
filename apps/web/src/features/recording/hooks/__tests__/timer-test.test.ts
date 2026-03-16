import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Scenario } from "../../types/scenario";
import { useScenarioPlayer } from "../useScenarioPlayer";

vi.mock("@/stores/loadingStore", () => ({
  useLoadingStore: (
    selector: (s: { setIsLoading: (v: boolean) => void }) => unknown,
  ) => selector({ setIsLoading: vi.fn() }),
}));

const makeScenario = (overrides?: Partial<Scenario>): Scenario => ({
  id: "test",
  title: "Test Scenario",
  viewport: { width: 390, height: 844 },
  settings: { theme: "dark" },
  states: [{ type: "user_message", text: "Hi", typingSpeed: 1, pauseAfter: 0 }],
  ...overrides,
});

describe("useScenarioPlayer timer tests", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("adds user message to messages after typing completes", async () => {
    const { result } = renderHook(() =>
      useScenarioPlayer(
        makeScenario({
          states: [
            { type: "user_message", text: "Hi", typingSpeed: 1, pauseAfter: 0 },
          ],
        }),
      ),
    );

    act(() => {
      result.current.play();
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].response).toBe("Hi");
  });
});
