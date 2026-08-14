/**
 * Regression test for a background executor run that dies mid-stream.
 *
 * A failed run publishes an error frame and then closes. The close is byte-for-byte
 * a clean one, so the handler finalized the placeholder with no error — status
 * `sent` — and a dead run rendered as a finished answer with no Retry.
 *
 * The suite missed it because nothing exercised the executor SSE path at all:
 * `chat-turn-failure.test.ts` covers the live chat turn's equivalent seam
 * (`resolveTurnOutcome`), and the executor path reaches the same outcome through
 * completely separate code.
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
import { useChatStore } from "@/stores/chatStore";

const CONVERSATION_ID = "conv-exec-1";
const TASK_ID = "task-exec-1";
const STREAM_ID = "stream-exec-1";

const frame = (payload: unknown): EventSourceMessage => ({
  id: "",
  event: "",
  retry: undefined,
  data: JSON.stringify(payload),
});

/** Drive the handler against a scripted stream, then read back the placeholder. */
const runStream = async (
  script: (onMessage: (event: EventSourceMessage) => void) => void,
  sawDone: boolean,
) => {
  vi.mocked(chatApi.subscribeToExecutorStream).mockImplementation(
    async (_streamId, onMessage, onClose) => {
      script(onMessage);
      onClose(sawDone);
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

  return useChatStore
    .getState()
    .messagesByConversation[CONVERSATION_ID]?.find((m) => m.id === TASK_ID);
};

describe("executor stream failure", () => {
  beforeEach(() => {
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: {},
    });
  });

  it("finalizes a run that published an error frame as failed, keeping its partial output", async () => {
    const message = await runStream((onMessage) => {
      onMessage(frame({ response: "half an answer" }));
      onMessage(frame({ error: "The executor crashed." }));
    }, false);

    expect(message?.status).toBe("failed");
    expect(message?.error).toBe("The executor crashed.");
    expect(message?.content).toBe("half an answer");
  });

  it("still finalizes a clean run as sent", async () => {
    const message = await runStream((onMessage) => {
      onMessage(frame({ response: "all done" }));
    }, true);

    expect(message?.status).toBe("sent");
    expect(message?.error).toBeNull();
  });
});
