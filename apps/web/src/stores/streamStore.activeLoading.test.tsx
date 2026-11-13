// @vitest-environment jsdom

/**
 * The below-bubble status line reflects real agent activity, never the HIL
 * approval gate: it shows nothing while a turn is paused on the user's decision,
 * and resumes with post-approval tool activity even if the approval flag is
 * still set — so a stuck flag can never freeze it on "Waiting for your approval".
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useChatStore } from "@/stores/chatStore";
import { useActiveLoading, useStreamStore } from "@/stores/streamStore";

const CONVO = "conv-1";

const resetStores = (): void => {
  for (const key of Object.keys(useStreamStore.getState().sessions)) {
    useStreamStore.getState().endSession(key);
  }
  for (const key of Object.keys(useStreamStore.getState().backgroundRuns)) {
    useStreamStore.getState().clearBackgroundLoading(key);
  }
  useChatStore.setState({ activeConversationId: CONVO });
};

describe("useActiveLoading", () => {
  afterEach(resetStores);

  it("hides the status line while a turn is paused on approval", () => {
    resetStores();
    const store = useStreamStore.getState();
    store.startSession(CONVO);
    // The gate arrived: spinner off, parked awaiting the user's decision.
    store.updateSession(CONVO, {
      phase: "awaiting_executor",
      spinnerActive: false,
      awaitingApproval: true,
      loadingText: "Posthog: deleting dashboard",
    });

    const { result } = renderHook(() => useActiveLoading());

    expect(result.current.isLoading).toBe(false);
    expect("awaitingApproval" in result.current).toBe(false);
  });

  it("shows post-approval activity even while the approval flag is still set", () => {
    resetStores();
    const store = useStreamStore.getState();
    store.startSession(CONVO);
    store.updateSession(CONVO, {
      phase: "awaiting_executor",
      spinnerActive: false,
      awaitingApproval: true,
    });
    // The resumed executor stream reports its tool activity via a background run
    // (setBackgroundLoading) — the line must surface it, not the stale gate.
    store.setBackgroundLoading(CONVO, "Running search", {
      toolName: "web_search",
    });

    const { result } = renderHook(() => useActiveLoading());

    expect(result.current.isLoading).toBe(true);
    expect(result.current.loadingText).toBe("Running search");
    expect(result.current.toolInfo?.toolName).toBe("web_search");
  });

  it("shows the streaming spinner text during a normal turn", () => {
    resetStores();
    const store = useStreamStore.getState();
    store.startSession(CONVO);
    store.updateSession(CONVO, {
      phase: "streaming",
      spinnerActive: true,
      loadingText: "Thinking",
    });

    const { result } = renderHook(() => useActiveLoading());

    expect(result.current.isLoading).toBe(true);
    expect(result.current.loadingText).toBe("Thinking");
  });
});
