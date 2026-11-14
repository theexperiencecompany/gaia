// @vitest-environment jsdom
/**
 * A retry of an answered message asks the server to answer the message the
 * server names as the retry target, in its place; a send that never landed is
 * resent unchanged, so the server's message id dedup holds.
 */
import { insertFrame, replyItem, userItem } from "@shared/conversation/testing";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRetryMessage } from "@/features/chat/hooks/useRetryMessage";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";

const { deliverRetry, deliverSend } = vi.hoisted(() => ({
  deliverRetry: vi.fn(),
  deliverSend: vi.fn(),
}));
vi.mock("@/features/chat/live/connection", () => ({
  deliverRetry,
  deliverSend,
}));

describe("useRetryMessage", () => {
  beforeEach(() => {
    deliverRetry.mockReset();
    deliverSend.mockReset();
    useLiveConversationStore.setState({ conversations: {} });
  });

  it("asks the server to answer again the message it names as the reply's retry target", async () => {
    useLiveConversationStore.getState().applyFrames("conv-1", [
      insertFrame(userItem("m-first", 1, "hello")),
      insertFrame(userItem("m-user", 2, "and then")),
      insertFrame({
        ...replyItem("r1", 3, "hi", "failed"),
        failure: "model_error",
        retry_target: "m-user",
      }),
    ]);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "r1"));

    expect(deliverRetry).toHaveBeenCalledExactlyOnceWith("conv-1", "m-user");
    expect(deliverSend).not.toHaveBeenCalled();
  });

  it("retries a user message as itself", async () => {
    useLiveConversationStore
      .getState()
      .applyFrames("conv-1", [insertFrame(userItem("m-user", 1, "summarise"))]);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "m-user"));

    expect(deliverRetry).toHaveBeenCalledExactlyOnceWith("conv-1", "m-user");
  });

  it("sends nothing for a reply the server names no retry target for", async () => {
    vi.spyOn(console, "error").mockImplementation(vi.fn());
    useLiveConversationStore
      .getState()
      .applyFrames("conv-1", [
        insertFrame(userItem("m-user", 1, "hello")),
        insertFrame(replyItem("r1", 2, "hi", "answered")),
      ]);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "r1"));

    expect(deliverRetry).not.toHaveBeenCalled();
    expect(deliverSend).not.toHaveBeenCalled();
  });

  it("resends a failed send as the same message instead of a new one", async () => {
    const store = useLiveConversationStore.getState();
    store.queueSend("conv-1", {
      body: { message_id: "m-lost", text: "hello" },
      fileData: [],
      failed: false,
    });
    store.setSendFailed("conv-1", "m-lost", true);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "m-lost"));

    expect(deliverSend).toHaveBeenCalledExactlyOnceWith("conv-1", "m-lost");
    expect(deliverRetry).not.toHaveBeenCalled();
  });
});
