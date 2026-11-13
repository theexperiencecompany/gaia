// @vitest-environment jsdom
/**
 * A retry of an answered message resends it naming the original in retry_of, so
 * the server can tell a resend from a new message; a send that never landed is
 * resent unchanged, so the server's message id dedup holds.
 */
import {
  entryFrame,
  reply,
  replySettled,
  userMessage,
} from "@shared/conversation/testing";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRetryMessage } from "@/features/chat/hooks/useRetryMessage";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";

const { sendMessage, deliverSend } = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  deliverSend: vi.fn(),
}));
vi.mock("@/features/chat/live/sendMessage", () => ({ sendMessage }));
vi.mock("@/features/chat/live/connection", () => ({ deliverSend }));

describe("useRetryMessage", () => {
  beforeEach(() => {
    sendMessage.mockReset();
    deliverSend.mockReset();
    useLiveConversationStore.setState({ conversations: {} });
  });

  it("resends the user message a reply answered, naming it in retry_of", async () => {
    useLiveConversationStore
      .getState()
      .applyFrames("conv-1", [
        entryFrame(1, userMessage("m-user", "hello")),
        entryFrame(2, reply("r1", "a1", "hi")),
        entryFrame(3, replySettled("r1", ["m-user"], 1)),
      ]);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "r1"));

    expect(sendMessage).toHaveBeenCalledWith(
      "hello",
      expect.objectContaining({ conversationId: "conv-1", retry_of: "m-user" }),
    );
    expect(deliverSend).not.toHaveBeenCalled();
  });

  it("resends the logged message's attachments and selections, on any device", async () => {
    const files = [
      {
        fileId: "f1",
        filename: "q3.pdf",
        url: "https://f/q3.pdf",
        type: "application/pdf",
      },
    ];
    useLiveConversationStore.getState().applyFrames("conv-1", [
      entryFrame(1, {
        ...userMessage("m-user", "summarise"),
        file_ids: ["f1"],
        files,
        selected_tool: "gmail_send",
        tool_category: "gmail",
      }),
    ]);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "m-user"));

    expect(sendMessage).toHaveBeenCalledWith(
      "summarise",
      expect.objectContaining({
        files,
        selected_tool: "gmail_send",
        tool_category: "gmail",
        retry_of: "m-user",
      }),
    );
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
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
