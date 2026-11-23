/**
 * A send that dies before the backend assigns ids must still leave evidence: the
 * failure path used to call `clearOptimisticMessage()` unconditionally, erasing a
 * new conversation's only record of the message on any API failure. Verified live
 * (API stopped): new-conversation send left an empty thread; existing conversations
 * correctly showed "Not delivered" + Retry. Pins the store flag; liveChat.render.test.tsx pins the bubble.
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
