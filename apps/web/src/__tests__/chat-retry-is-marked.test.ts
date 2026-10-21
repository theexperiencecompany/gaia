// @vitest-environment jsdom
/**
 * A retry resends its message marked as a retry, so the server's
 * chat:message_submitted can tell a resend from a new message.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRetryMessage } from "@/features/chat/hooks/useRetryMessage";
import { useChatStore } from "@/stores/chatStore";

const sendMessage = vi.fn();
vi.mock("@/hooks/useSendMessage", () => ({
  useSendMessage: () => sendMessage,
}));

describe("useRetryMessage", () => {
  beforeEach(() => sendMessage.mockReset());

  it("resends the user message as a retry", async () => {
    useChatStore.setState({
      messagesByConversation: {
        "conv-1": [
          { id: "m-user", role: "user", content: "hello" },
          { id: "m-bot", role: "assistant", content: "" },
        ],
      },
    } as unknown as Partial<ReturnType<typeof useChatStore.getState>>);
    const { result } = renderHook(() => useRetryMessage());

    await act(() => result.current.retryMessage("conv-1", "m-bot"));

    expect(sendMessage).toHaveBeenCalledWith(
      "hello",
      expect.objectContaining({ conversationId: "conv-1", isRetry: true }),
    );
  });
});
