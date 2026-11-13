/**
 * Regression: on a HIL resume the handler folds the stream into the ORIGINAL bot
 * message, seeding its accumulator from that message's content. A resumed
 * executor stream emits no `response` frames, so that seed never advances — yet
 * every flush re-stamped it over `content`, reverting the comms narration the
 * backend had just saved and broadcast.
 */
import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putMessage: vi.fn().mockResolvedValue(undefined),
    getAllConversations: vi.fn().mockResolvedValue([]),
    getAllMessages: vi.fn().mockResolvedValue([]),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { subscribeToExecutorStream: vi.fn() },
}));

import { chatApi } from "@/features/chat/api/chatApi";
import { createExecutorStreamHandler } from "@/features/chat/hooks/useExecutorStream";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const CONVERSATION_ID = "conv-resume-1";
const TASK_ID = "task-resume-1";
const STREAM_ID = "stream-resume-1";
const BOT_MESSAGE_ID = "bot-msg-resume-1";

const PRE_RESUME_TEXT = "Working on it, should be gone in a sec.";
const NARRATION = "Cleared. That event is off your calendar.";

const frame = (payload: unknown): EventSourceMessage => ({
  id: "",
  event: "",
  retry: undefined,
  data: JSON.stringify(payload),
});

const parkedBotMessage = (): IMessage =>
  ({
    id: BOT_MESSAGE_ID,
    conversationId: CONVERSATION_ID,
    content: PRE_RESUME_TEXT,
    role: "assistant",
    status: "sent",
    createdAt: new Date(),
    updatedAt: new Date(),
    messageId: BOT_MESSAGE_ID,
    tool_data: null,
  }) as unknown as IMessage;

describe("executor stream HIL resume", () => {
  beforeEach(() => {
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: { [CONVERSATION_ID]: [parkedBotMessage()] },
    });
  });

  it("keeps the comms narration that lands mid-resume", async () => {
    vi.mocked(chatApi.subscribeToExecutorStream).mockImplementation(
      async (_streamId, onMessage, onClose) => {
        // A resumed executor reports tool activity, never response text.
        onMessage(frame({ tool_data: [{ tool_name: "tool_calls_data" }] }));
        // The backend's silent narration arrives over the WebSocket.
        useChatStore.getState().addOrUpdateMessage({
          ...parkedBotMessage(),
          content: NARRATION,
        });
        onClose(true);
      },
    );

    await createExecutorStreamHandler(
      new Set(),
      new Set(),
    )({
      type: "executor.stream_started",
      stream_id: STREAM_ID,
      conversation_id: CONVERSATION_ID,
      task_id: TASK_ID,
      bot_message_id: BOT_MESSAGE_ID,
    });

    const message = useChatStore
      .getState()
      .messagesByConversation[CONVERSATION_ID]?.find(
        (m) => m.id === BOT_MESSAGE_ID,
      );
    expect(message?.content).toBe(NARRATION);
  });
});
