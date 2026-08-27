/**
 * Regression test for the approval indicator leaking across conversations.
 *
 * The bug: settling an approval walked EVERY session in the stream store and
 * cleared `awaitingApproval` on all of them. With two conversations each paused
 * on their own gate, deciding one flipped the other's amber "Waiting for your
 * approval" pill to "Resuming" — the untouched conversation looked like it had
 * carried on when it was in fact still blocked on the user.
 *
 * The fix scopes the clear to one session key, so these pin that the named
 * session settles and every other session is left exactly as it was.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { useStreamStore } from "@/stores/streamStore";

const startAwaitingSession = (key: string): void => {
  const store = useStreamStore.getState();
  store.startSession(key);
  store.updateSession(key, {
    awaitingApproval: true,
    loadingText: "Waiting for your approval",
    toolInfo: { integrationName: "posthog", toolName: "delete_dashboard" },
  });
};

describe("clearAwaitingApproval", () => {
  beforeEach(() => {
    for (const key of Object.keys(useStreamStore.getState().sessions)) {
      useStreamStore.getState().endSession(key);
    }
  });

  it("settles only the conversation whose gate was decided", () => {
    startAwaitingSession("conv-a");
    startAwaitingSession("conv-b");

    useStreamStore.getState().clearAwaitingApproval("conv-a");

    const { sessions } = useStreamStore.getState();
    expect(sessions["conv-a"]?.awaitingApproval).toBe(false);
    expect(sessions["conv-a"]?.loadingText).toBe("Resuming");
    // The other conversation is still blocked on a decision the user has not
    // made — its indicator must keep asking.
    expect(sessions["conv-b"]?.awaitingApproval).toBe(true);
    expect(sessions["conv-b"]?.loadingText).toBe("Waiting for your approval");
  });

  it("clears the gated tool's label with the awaiting state", () => {
    startAwaitingSession("conv-a");

    useStreamStore.getState().clearAwaitingApproval("conv-a");

    // toolInfo prefixes the label with the gated tool's integration
    // ("Posthog: Resuming"), and that tool is done.
    expect(
      useStreamStore.getState().sessions["conv-a"]?.toolInfo,
    ).toBeUndefined();
  });

  it("leaves a session that was not awaiting untouched", () => {
    const store = useStreamStore.getState();
    store.startSession("conv-a");
    store.updateSession("conv-a", { loadingText: "Thinking" });

    store.clearAwaitingApproval("conv-a");

    expect(useStreamStore.getState().sessions["conv-a"]?.loadingText).toBe(
      "Thinking",
    );
  });

  it("is a no-op for a key with no session", () => {
    expect(() =>
      useStreamStore.getState().clearAwaitingApproval("does-not-exist"),
    ).not.toThrow();
  });
});
