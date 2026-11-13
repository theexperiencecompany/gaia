/**
 * A background subagent streams on a stream of its own into the turn that
 * dispatched it. Its frames — above all an approval card raised after that turn
 * ended, and the resumed run's cards after the decision — must land in THAT
 * message, beside the cards the turn's own run is still writing, without taking
 * over the message's text or status.
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

const CONVERSATION_ID = "conv-subagent-fold";
const TURN_MESSAGE_ID = "bot-msg-turn";
const SUBAGENT_ID = "row-flowchart";
const APPROVAL_ID = "appr-flowchart";
const TURN_TEXT = "Started the flowchart in the background.";

type Frame = Record<string, unknown>;

const sse = (payload: Frame): EventSourceMessage => ({
  id: "",
  event: "",
  retry: undefined,
  data: JSON.stringify(payload),
});

const executorCard = {
  tool_name: "tool_calls_data",
  tool_category: "spawn_subagent",
  data: { tool_name: "spawn_subagent", tool_call_id: "tc_spawn" },
};

const turnMessage = (): IMessage =>
  ({
    id: TURN_MESSAGE_ID,
    conversationId: CONVERSATION_ID,
    content: TURN_TEXT,
    role: "assistant",
    status: "sent",
    createdAt: new Date(),
    updatedAt: new Date(),
    messageId: TURN_MESSAGE_ID,
    tool_data: [executorCard],
  }) as unknown as IMessage;

const subagentStart: Frame = {
  subagent_start: {
    subagent_id: SUBAGENT_ID,
    subagent_name: "draw the flowchart",
    agent_type: "spawned",
    started_at: "2026-09-23T10:00:00.000Z",
    tool_category: "spawn_subagent",
  },
};

const subagentCall = (toolCallId: string): Frame => ({
  tool_data: {
    tool_name: "tool_calls_data",
    tool_category: "creative",
    subagent_id: SUBAGENT_ID,
    data: {
      tool_name: "create_flowchart",
      tool_category: "creative",
      message: "Creating a flowchart",
      tool_call_id: toolCallId,
    },
  },
});

const approvalCard = (status: string): Frame => ({
  tool_data: {
    tool_name: "approval_request",
    tool_category: "hil",
    data: {
      approval_id: APPROVAL_ID,
      tool_call_id: "tc_gated",
      gated_tool_name: "create_flowchart",
      integration_name: null,
      summary: "Create a flowchart",
      args: {},
      status,
    },
  },
});

/** Run one announced subagent stream to its close, replaying frames in order. */
const runSubagentStream = async (
  streamId: string,
  frames: Frame[],
  midStream?: () => void,
) => {
  vi.mocked(chatApi.subscribeToExecutorStream).mockImplementationOnce(
    async (_streamId, onMessage, onClose) => {
      frames.forEach((frame, index) => {
        onMessage(sse(frame));
        if (index === 0) midStream?.();
      });
      onClose(true);
    },
  );
  await createExecutorStreamHandler(
    new Set(),
    new Set(),
  )({
    type: "executor.stream_started",
    stream_id: streamId,
    conversation_id: CONVERSATION_ID,
    task_id: SUBAGENT_ID,
    bot_message_id: TURN_MESSAGE_ID,
    kind: "subagent",
  });
};

const turn = (): IMessage => {
  const found = useChatStore
    .getState()
    .messagesByConversation[CONVERSATION_ID]?.find(
      (m) => m.id === TURN_MESSAGE_ID,
    );
  if (!found) throw new Error("the turn's message is gone");
  return found;
};

type Entry = { tool_name: string; data: Record<string, unknown> };

const entries = (): Entry[] => (turn().tool_data ?? []) as unknown as Entry[];

const cards = () => entries().filter((e) => e.tool_name === "approval_request");

const groupCalls = (): string[] => {
  const group = entries().find((e) => e.tool_name === "subagent_group");
  const calls = (group?.data.tool_calls ?? []) as { tool_call_id: string }[];
  return calls.map((c) => c.tool_call_id);
};

describe("a background subagent's own stream", () => {
  beforeEach(() => {
    vi.mocked(chatApi.subscribeToExecutorStream).mockReset();
    useChatStore.setState({
      activeConversationId: CONVERSATION_ID,
      messagesByConversation: { [CONVERSATION_ID]: [turnMessage()] },
    });
  });

  it("raises its approval card inside the turn that dispatched it", async () => {
    await runSubagentStream("subagent-stream-1", [
      subagentStart,
      subagentCall("tc_retrieve"),
      approvalCard("pending"),
    ]);

    expect(entries().map((e) => e.tool_name)).toEqual([
      "tool_calls_data",
      "subagent_group",
      "approval_request",
    ]);
    expect(cards()[0].data.status).toBe("pending");
    // The turn's text and status stay the turn's own.
    expect(turn().content).toBe(TURN_TEXT);
    expect(turn().status).toBe("sent");
  });

  it("keeps the cards the turn's own run writes while it streams", async () => {
    const lateExecutorCard = {
      tool_name: "tool_calls_data",
      tool_category: "general",
      data: { tool_name: "read", tool_call_id: "tc_read" },
    };
    await runSubagentStream(
      "subagent-stream-1",
      [subagentStart, approvalCard("pending")],
      () => {
        useChatStore.getState().updateMessageInPlace({
          ...turn(),
          tool_data: [
            ...(turn().tool_data ?? []),
            lateExecutorCard,
          ] as IMessage["tool_data"],
        });
      },
    );

    expect(entries().some((e) => e.data.tool_call_id === "tc_read")).toBe(true);
    expect(cards()).toHaveLength(1);
  });

  it("settles the card in place when the resumed run reports the decision", async () => {
    await runSubagentStream("subagent-stream-1", [
      subagentStart,
      subagentCall("tc_retrieve"),
      approvalCard("pending"),
    ]);
    await runSubagentStream("subagent-stream-2", [
      subagentStart,
      approvalCard("approved"),
      subagentCall("tc_gated"),
      { subagent_end: { subagent_id: SUBAGENT_ID, duration_ms: 1200 } },
    ]);

    expect(cards()).toHaveLength(1);
    expect(cards()[0].data.status).toBe("approved");
    expect(
      entries().filter((e) => e.tool_name === "subagent_group"),
    ).toHaveLength(1);
    expect(groupCalls()).toEqual(["tc_retrieve", "tc_gated"]);
    expect(turn().content).toBe(TURN_TEXT);
  });
});
