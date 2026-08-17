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
 *
 * The chain these pin is store flag -> conversation mapping -> bubble props. The
 * JSX itself is NOT covered: apps/web has no DOM test environment, so "the label
 * and Retry button are on screen" rests on the live-stack run above, not on a
 * rendered assertion.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  mapOptimisticMessageToConversationMessage,
  mapStoredMessageToConversationMessage,
} from "@/features/chat/hooks/useConversation";
import { getMessageProps } from "@/features/chat/utils/messagePropsUtils";
import type { IMessage } from "@/lib/db/chatDb";
import { type OptimisticMessage, useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

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

describe("failed message mapping", () => {
  it("carries the optimistic failure into the conversation message", () => {
    const mapped = mapOptimisticMessageToConversationMessage({
      ...optimistic(),
      failed: true,
    });

    expect(mapped.failed).toBe(true);
    expect(mapped.response).toBe("the message the user typed");
  });

  it("leaves a healthy optimistic message unflagged", () => {
    expect(
      mapOptimisticMessageToConversationMessage(optimistic()).failed,
    ).toBeUndefined();
  });

  it("derives failed from a stored message's status", () => {
    const stored = (status: IMessage["status"]): IMessage => ({
      id: "user-1",
      conversationId: "conv-1",
      content: "the message the user typed",
      role: "user",
      status,
      createdAt: new Date("2026-01-01T00:00:00Z"),
      updatedAt: new Date("2026-01-01T00:00:00Z"),
    });

    expect(mapStoredMessageToConversationMessage(stored("failed")).failed).toBe(
      true,
    );
    expect(mapStoredMessageToConversationMessage(stored("sent")).failed).toBe(
      false,
    );
  });
});

describe("failed user bubble props", () => {
  // The "Not delivered" label renders on `failed`, and Retry on `onRetry` — the
  // two props the bubble needs before the failure is actionable on screen.
  it("hands the bubble the failed flag and a bound retry callback", () => {
    const message: MessageType = {
      type: "user",
      response: "the message the user typed",
      message_id: "user-1",
      failed: true,
    };
    const onRetry = vi.fn();

    const props = getMessageProps(message, "user", {
      setImageData: vi.fn(),
      setOpenGeneratedImage: vi.fn(),
      setOpenMemoryModal: vi.fn(),
      onRetry,
    });

    expect(props.failed).toBe(true);
    props.onRetry?.();
    expect(onRetry).toHaveBeenCalledWith("user-1");
  });
});
