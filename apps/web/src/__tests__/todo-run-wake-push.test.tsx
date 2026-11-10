// @vitest-environment jsdom
/**
 * Regression: the live new-message push took every message for a bot reply, so a
 * tracked todo's wake (the user's side of its run) would have landed as GAIA's.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putMessage: vi.fn().mockResolvedValue(undefined),
    replaceMessage: vi.fn().mockResolvedValue(undefined),
    getAllConversations: vi.fn().mockResolvedValue([]),
    getAllMessages: vi.fn().mockResolvedValue([]),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/features/chat/stream/unread", () => ({
  isViewingConversation: () => true,
  markConversationUnread: vi.fn(),
}));

import { useBgMessageWebSocket } from "@/features/chat/hooks/useBgMessageWebSocket";
import { db } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

const CONVERSATION_ID = "todo-chat-1";
const WAKE = {
  kind: "schedule",
  trigger_names: [],
  approval_summary: null,
} as const;

const pushed = () => {
  renderHook(() => useBgMessageWebSocket());
  const [, handler] =
    vi
      .mocked(wsManager.on)
      .mock.calls.find(([event]) => event === "conversation.new_message") ?? [];
  if (!handler) throw new Error("the hook registered no new-message handler");
  return handler as (event: unknown) => Promise<void>;
};

describe("a tracked todo run's wake pushed to an open chat", () => {
  beforeEach(() => {
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: {},
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("lands on the user's side with what woke the run", async () => {
    await pushed()({
      type: "conversation.new_message",
      conversation_id: CONVERSATION_ID,
      message: {
        type: "user",
        response: "",
        message_id: "wake-1",
        date: "2026-10-31T14:05:00Z",
        todo_run_wake: WAKE,
      },
    });

    const [[saved]] = vi.mocked(db.putMessage).mock.calls;
    expect(saved).toMatchObject({
      id: "wake-1",
      role: "user",
      content: "",
      todoRunWake: WAKE,
    });
    const shown = useChatStore
      .getState()
      .messagesByConversation[CONVERSATION_ID]?.find((m) => m.id === "wake-1");
    expect(shown?.role).toBe("user");
  });

  it("does not end the wait for GAIA's reply", async () => {
    const endSession = vi.fn();
    useStreamStore.setState({
      sessions: {
        [CONVERSATION_ID]: { phase: "awaiting_executor" },
      } as never,
      endSession,
    } as never);

    await pushed()({
      type: "conversation.new_message",
      conversation_id: CONVERSATION_ID,
      message: {
        type: "user",
        response: "",
        message_id: "wake-2",
        date: "2026-10-31T14:06:00Z",
        todo_run_wake: WAKE,
      },
    });

    expect(endSession).not.toHaveBeenCalled();
  });
});
