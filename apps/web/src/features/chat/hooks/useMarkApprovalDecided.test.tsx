// @vitest-environment jsdom

/**
 * Regression: the clear keyed off the route param, which is stale for a
 * replaceState'd new chat, so deciding a gate never cleared the live session and
 * the approval flag stayed stuck. It must key off `activeConversationId`.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import { useChatStore } from "@/stores/chatStore";
import { PENDING_KEY_PREFIX, useStreamStore } from "@/stores/streamStore";

const CONVO = "conv-live";

const resetStores = (): void => {
  for (const key of Object.keys(useStreamStore.getState().sessions)) {
    useStreamStore.getState().endSession(key);
  }
  useChatStore.setState({ activeConversationId: null });
};

describe("useMarkApprovalDecided", () => {
  afterEach(resetStores);

  it("clears the active conversation's gate without a matching route param", () => {
    resetStores();
    const store = useStreamStore.getState();
    store.startSession(CONVO);
    store.updateSession(CONVO, { awaitingApproval: true });
    // The route param is absent (a fresh chat rewrote the URL); the live session
    // is only reachable via activeConversationId.
    useChatStore.setState({ activeConversationId: CONVO });

    const { result } = renderHook(() => useMarkApprovalDecided());
    result.current();

    expect(useStreamStore.getState().sessions[CONVO]?.awaitingApproval).toBe(
      false,
    );
  });

  it("clears the card's conversation when explicitly passed, not the active one", () => {
    resetStores();
    const cardConvo = "conv-card";
    const store = useStreamStore.getState();
    store.startSession(CONVO);
    store.updateSession(CONVO, { awaitingApproval: true });
    store.startSession(cardConvo);
    store.updateSession(cardConvo, { awaitingApproval: true });
    useChatStore.setState({ activeConversationId: CONVO });

    const { result } = renderHook(() => useMarkApprovalDecided());
    result.current(cardConvo);

    expect(
      useStreamStore.getState().sessions[cardConvo]?.awaitingApproval,
    ).toBe(false);
    expect(useStreamStore.getState().sessions[CONVO]?.awaitingApproval).toBe(
      true,
    );
  });

  it("falls back to the pending new-chat key when nothing is active", () => {
    resetStores();
    // startSession only records pendingNewConversationKey for a "pending:" key,
    // which is what the hook falls back to when nothing is active.
    const pendingKey = `${PENDING_KEY_PREFIX}abc`;
    const store = useStreamStore.getState();
    store.startSession(pendingKey);
    store.updateSession(pendingKey, { awaitingApproval: true });
    useChatStore.setState({ activeConversationId: null });

    const { result } = renderHook(() => useMarkApprovalDecided());
    result.current();

    expect(
      useStreamStore.getState().sessions[pendingKey]?.awaitingApproval,
    ).toBe(false);
  });
});
