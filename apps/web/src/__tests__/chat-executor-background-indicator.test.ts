/**
 * Background-run indicator for detached executor streams.
 *
 * After an approval tap the chat SSE is long closed, so no turn session drives
 * the loading indicator — the user stared at a dead chat while the ticket run
 * streamed. Detached runs now track their own indicator state (scoped per
 * conversation), updated from each tool frame and cleared on close/error.
 */
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

import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import { chatApi } from "@/features/chat/api/chatApi";
import { createExecutorStreamHandler } from "@/features/chat/hooks/useExecutorStream";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

const CONVERSATION_ID = "conv-bg-1";
const TASK_ID = "task-bg-1";
const STREAM_ID = "stream-bg-1";

const frame = (payload: unknown): EventSourceMessage => ({
  id: "",
  event: "",
  retry: undefined,
  data: JSON.stringify(payload),
});

describe("background run indicator", () => {
  beforeEach(() => {
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: {},
    });
    useStreamStore.setState({
      sessions: {},
      backgroundRuns: {},
      auxLoading: null,
    });
    vi.mocked(chatApi.subscribeToExecutorStream).mockReset();
  });

  it("marks the conversation active while a detached run streams", async () => {
    let close!: (ok: boolean) => void;
    vi.mocked(chatApi.subscribeToExecutorStream).mockImplementation(
      async (_streamId, _message, onClose) => {
        close = onClose;
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
    });

    expect(
      useStreamStore.getState().backgroundRuns[CONVERSATION_ID],
    ).toBeDefined();

    close(true);
    expect(
      useStreamStore.getState().backgroundRuns[CONVERSATION_ID],
    ).toBeUndefined();
  });

  it("updates the label from tool frames and clears on close", async () => {
    let onMessage!: (event: EventSourceMessage) => void;
    let onClose!: (ok: boolean) => void;
    vi.mocked(chatApi.subscribeToExecutorStream).mockImplementation(
      async (_streamId, message, close) => {
        onMessage = message;
        onClose = close;
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
    });

    onMessage(
      frame({
        progress: {
          message: "Calling calendar",
          tool_name: "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
          tool_category: "calendar",
        },
      }),
    );
    const active = useStreamStore.getState().backgroundRuns[CONVERSATION_ID];
    expect(active?.loadingText).toBe("Calling calendar");
    expect(active?.toolInfo?.toolName).toBe(
      "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
    );

    onClose(true);
    expect(
      useStreamStore.getState().backgroundRuns[CONVERSATION_ID],
    ).toBeUndefined();
  });

  it("ignores streams for other conversations", async () => {
    await createExecutorStreamHandler(
      new Set(),
      new Set(),
    )({
      type: "executor.stream_started",
      stream_id: "stream-other",
      conversation_id: "conv-other",
      task_id: "task-other",
    });

    expect(useStreamStore.getState().backgroundRuns).toEqual({});
  });
});
