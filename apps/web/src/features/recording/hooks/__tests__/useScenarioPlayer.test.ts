// apps/web/src/features/recording/hooks/__tests__/useScenarioPlayer.test.ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { useScenarioPlayer } from "../useScenarioPlayer";
import type { Scenario } from "../../types/scenario";

// Mock the loadingStore with a stable setIsLoading reference to prevent
// useCallback dependency churn across renders
vi.mock("@/stores/loadingStore", () => {
  const stableSetIsLoading = vi.fn();
  return {
    useLoadingStore: (
      selector: (s: { setIsLoading: (v: boolean) => void }) => unknown,
    ) => selector({ setIsLoading: stableSetIsLoading }),
  };
});

// Create scenarios OUTSIDE renderHook so they are stable references.
// If created inside renderHook, scenario.states gets a new array reference
// on every re-render, causing the useEffect to re-fire infinitely.
const makeScenario = (overrides?: Partial<Scenario>): Scenario => ({
  id: "test",
  title: "Test Scenario",
  viewport: { width: 390, height: 844 },
  settings: { theme: "dark" },
  states: [
    { type: "user_message", text: "Hi", typingSpeed: 50, pauseAfter: 0 },
  ],
  ...overrides,
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useScenarioPlayer", () => {
  it("starts in idle phase", () => {
    const scenario = makeScenario();
    const { result } = renderHook(() => useScenarioPlayer(scenario));
    expect(result.current.phase).toBe("idle");
  });

  it("starts with empty messages", () => {
    const scenario = makeScenario();
    const { result } = renderHook(() => useScenarioPlayer(scenario));
    expect(result.current.messages).toEqual([]);
  });

  it("transitions to playing when play() is called", () => {
    const scenario = makeScenario();
    const { result } = renderHook(() => useScenarioPlayer(scenario));
    act(() => {
      result.current.play();
    });
    expect(result.current.phase).toBe("playing");
  });

  it("shows partial message while user message is typing", async () => {
    const scenario = makeScenario({
      states: [
        {
          type: "user_message",
          text: "Hello",
          typingSpeed: 10,
          pauseAfter: 0,
        },
      ],
    });

    const { result } = renderHook(() => useScenarioPlayer(scenario));

    act(() => {
      result.current.play();
    });

    await waitFor(() => {
      expect(result.current.partialMessage).not.toBeNull();
    });

    expect(result.current.partialMessage?.type).toBe("user");
  });

  it("adds user message to messages after typing completes", async () => {
    const scenario = makeScenario({
      states: [
        { type: "user_message", text: "Hi", typingSpeed: 10, pauseAfter: 0 },
      ],
    });

    const { result } = renderHook(() => useScenarioPlayer(scenario));

    act(() => {
      result.current.play();
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    expect(result.current.messages[0].response).toBe("Hi");
    expect(result.current.messages[0].type).toBe("user");
  });

  it("resets to idle state when reset() is called", async () => {
    const scenario = makeScenario();
    const { result } = renderHook(() => useScenarioPlayer(scenario));

    act(() => {
      result.current.play();
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.phase).toBe("idle");
    expect(result.current.partialMessage).toBeNull();
  });

  it("generates unique message_ids for each message", async () => {
    const scenario = makeScenario({
      states: [
        { type: "user_message", text: "A", typingSpeed: 10, pauseAfter: 0 },
        { type: "user_message", text: "B", typingSpeed: 10, pauseAfter: 0 },
      ],
    });

    const { result } = renderHook(() => useScenarioPlayer(scenario));

    act(() => {
      result.current.play();
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(2);
    });

    const ids = result.current.messages.map((m) => m.message_id);
    // All IDs should be unique
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("pauses playback when pause() is called", () => {
    const scenario = makeScenario();
    const { result } = renderHook(() => useScenarioPlayer(scenario));

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
    const scenario = makeScenario({
      states: [
        { type: "user_message", text: "Hi", typingSpeed: 10, pauseAfter: 0 },
      ],
    });

    const { result } = renderHook(() => useScenarioPlayer(scenario));

    act(() => {
      result.current.play();
    });

    await waitFor(
      () => {
        expect(result.current.phase).toBe("done");
      },
      { timeout: 5000 },
    );
  });
});
