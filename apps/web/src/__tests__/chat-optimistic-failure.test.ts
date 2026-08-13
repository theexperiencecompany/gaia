/**
 * A send that dies before the backend assigns any ids must still leave evidence.
 *
 * For a brand-new conversation the optimistic message is the ONLY record of what
 * the user typed — nothing is in IndexedDB and no conversation exists yet. The
 * failure path used to call `clearOptimisticMessage()` unconditionally, so an
 * API that was down, rate-limiting, or rejecting auth erased the user's message
 * from the thread entirely, leaving a toast that faded in a few seconds.
 *
 * Verified against a live stack: with the API stopped, a new-conversation send
 * left a completely empty thread. In an existing conversation the same failure
 * correctly showed "Not delivered" + Retry, because there the user message is
 * persisted and gets flipped to `failed` instead.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { type OptimisticMessage, useChatStore } from "@/stores/chatStore";

const optimistic = (): OptimisticMessage => ({
  id: "optimistic-1",
  conversationId: null,
  content: "the message the user typed",
  role: "user",
  createdAt: new Date("2026-01-01T00:00:00Z"),
});

describe("optimistic message failure", () => {
  beforeEach(() => {
    useChatStore.setState({ optimisticMessage: null });
  });

  it("keeps the message and marks it failed", () => {
    const store = useChatStore.getState();
    store.setOptimisticMessage(optimistic());

    store.markOptimisticMessageFailed();

    const current = useChatStore.getState().optimisticMessage;
    expect(current).not.toBeNull();
    expect(current?.content).toBe("the message the user typed");
    expect(current?.failed).toBe(true);
  });

  it("is a no-op when there is no optimistic message", () => {
    useChatStore.getState().markOptimisticMessageFailed();

    expect(useChatStore.getState().optimisticMessage).toBeNull();
  });

  it("clearOptimisticMessage still removes it outright", () => {
    const store = useChatStore.getState();
    store.setOptimisticMessage(optimistic());

    store.clearOptimisticMessage();

    expect(useChatStore.getState().optimisticMessage).toBeNull();
  });
});
