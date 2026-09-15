/**
 * A send that dies before the backend assigns ids must still leave evidence: the
 * failure path used to call `clearOptimisticMessage()` unconditionally, erasing a
 * new conversation's only record of the message on any API failure. Verified live
 * (API stopped): new-conversation send left an empty thread; existing conversations
 * correctly showed "Not delivered" + Retry. Pins store flag → mapping → props; JSX itself is unverified (no DOM test env).
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
