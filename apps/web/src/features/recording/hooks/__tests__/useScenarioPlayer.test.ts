// apps/web/src/features/recording/hooks/__tests__/useScenarioPlayer.test.ts
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useScenarioPlayer } from "../useScenarioPlayer";
import type { Scenario } from "../../types/scenario";

// Mock the loadingStore
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
  states: [
    { type: "user_message", text: "Hi", typingSpeed: 1, pauseAfter: 0 },
  ],
  ...overrides,
});

describe("useScenarioPlayer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("starts in idle phase", () => {
    const { result } = renderHook(() => useScenarioPlayer(makeScenario()));
    expect(result.current.phase).toBe("idle");
  });

  it("starts with empty messages", () => {
    const { result } = renderHook(() => useScenarioPlayer(makeScenario()));
    expect(result.current.messages).toEqual([]);
  });

  it("transitions to playing when play() is called", () => {
    const { result } = renderHook(() => useScenarioPlayer(makeScenario()));
    act(() => {
      result.current.play();
    });
    expect(result.current.phase).toBe("playing");
  });

  it("shows partial message while user message is typing", async () => {
    const { result } = renderHook(() =>
      useScenarioPlayer(
        makeScenario({
          states: [
            {
              type: "user_message",
              text: "Hello",
              typingSpeed: 100,
              pauseAfter: 0,
            },
          ],
        }),
      ),
    );

    act(() => {
      result.current.play();
    });

    // After 1 char typed (100ms)
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(result.current.partialMessage).not.toBeNull();
    expect(result.current.partialMessage?.type).toBe("user");
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
    expect(result.current.messages[0].type).toBe("user");
  });

  it("resets to idle state when reset() is called", async () => {
    const { result } = renderHook(() => useScenarioPlayer(makeScenario()));

    act(() => {
      result.current.play();
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.phase).toBe("idle");
    expect(result.current.partialMessage).toBeNull();
  });

  it("generates unique message_ids for each message", async () => {
    const { result } = renderHook(() =>
      useScenarioPlayer(
        makeScenario({
          states: [
            { type: "user_message", text: "A", typingSpeed: 1, pauseAfter: 0 },
            { type: "user_message", text: "B", typingSpeed: 1, pauseAfter: 0 },
          ],
        }),
      ),
    );

    act(() => {
      result.current.play();
    });

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    const ids = result.current.messages.map((m) => m.message_id);
    // All IDs should be unique
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("pauses playback when pause() is called", () => {
    const { result } = renderHook(() => useScenarioPlayer(makeScenario()));

    act(() => {
      result.current.play();
    });
    expect(result.current.phase).toBe("playing");

    act(() => {
      result.current.pause();
    });
    expect(result.current.phase).toBe("idle");
  });

  it("transitions to done phase after all states complete", async () => {
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
      vi.advanceTimersByTime(5000);
    });

    expect(result.current.phase).toBe("done");
  });
});
