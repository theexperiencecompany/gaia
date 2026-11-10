/**
 * Regression: a detached run's final message vanished from the open chat half a
 * second after it arrived. The stream saves its placeholder to IndexedDB on a
 * 500ms throttle, and that deferred write carried the snapshot taken before the
 * final message replaced the placeholder under the same id — so it wrote the
 * empty placeholder back over the report (a tracked todo's run lands its report
 * within that window). Missed because no test let the final message arrive while
 * a throttled write was still pending.
 */
import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { db, type IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const CONVERSATION_ID = "todo-chat-1";
const TASK_ID = "task-1";
const REPORT = "Deploy is green: all 3 checks passed.";

const frame = (payload: unknown): EventSourceMessage => ({
  id: "",
  event: "",
  retry: undefined,
  data: JSON.stringify(payload),
});

/** What useBgMessageWebSocket leaves in the store when the run's final message lands. */
const landFinalMessage = () => {
  const final: IMessage = {
    id: TASK_ID,
    conversationId: CONVERSATION_ID,
    content: REPORT,
    role: "assistant",
    status: "sent",
    createdAt: new Date(),
    updatedAt: new Date(),
    messageId: TASK_ID,
    tool_data: null,
  };
  useChatStore.getState().addOrUpdateMessage(final);
};

const message = () =>
  useChatStore
    .getState()
    .messagesByConversation[CONVERSATION_ID]?.find((m) => m.id === TASK_ID);

describe("the final message of a detached run", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("is never overwritten by the placeholder snapshot the stream had pending", async () => {
    vi.mocked(chatApi.subscribeToExecutorStream).mockImplementation(
      async (_streamId, onMessage, onClose) => {
        onMessage(frame({ progress: { message: "Reviewing tracked work" } }));
        // The report lands before the stream closes, inside the write throttle.
        landFinalMessage();
        vi.mocked(db.putMessage).mockClear();
        await vi.advanceTimersByTimeAsync(600);
        onClose(true);
      },
    );

    await createExecutorStreamHandler(
      new Set(),
      new Set(),
    )({
      type: "executor.stream_started",
      stream_id: "stream-1",
      conversation_id: CONVERSATION_ID,
      task_id: TASK_ID,
    });

    // No write may carry the empty placeholder back over the report.
    for (const [written] of vi.mocked(db.putMessage).mock.calls) {
      expect(written.content).toBe(REPORT);
    }
    expect(message()?.content).toBe(REPORT);
    expect(message()?.status).toBe("sent");
  });
});
