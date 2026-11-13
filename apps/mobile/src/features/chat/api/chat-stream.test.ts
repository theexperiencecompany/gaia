import type { ChatStreamEvent } from "@gaia/shared/chat";
import { describe, expect, it, vi } from "vitest";
import type { SSECallbacks } from "@/lib/sse-client";
import { fetchChatStream, type StreamCallbacks } from "./chat-stream";

const { sse } = vi.hoisted(() => ({
  sse: { callbacks: null as SSECallbacks | null },
}));

vi.mock("@/lib/sse-client", () => ({
  createSSEConnection: vi.fn(async (_endpoint: string, cbs: SSECallbacks) => {
    sse.callbacks = cbs;
    return new AbortController();
  }),
}));

/** Opens a stream and feeds it one data frame per payload, as the backend would. */
async function stream(
  payloads: object[],
  callbacks: Partial<StreamCallbacks> = {},
): Promise<void> {
  await fetchChatStream(
    { message: "hi", conversationId: "conv-1" },
    { onDone: vi.fn(), ...callbacks },
  );
  for (const payload of payloads) {
    sse.callbacks?.onMessage({ data: JSON.stringify(payload) });
  }
}

describe("fetchChatStream — a turn's identity", () => {
  it("hands over the server message ids of a turn in an existing conversation", async () => {
    const onMessageIds = vi.fn();
    const onConversationCreated = vi.fn();

    await stream(
      [{ user_message_id: "u-1", bot_message_id: "b-1", stream_id: "s-1" }],
      { onMessageIds, onConversationCreated },
    );

    expect(onMessageIds).toHaveBeenCalledWith("u-1", "b-1");
    expect(onConversationCreated).not.toHaveBeenCalled();
  });

  it("announces a new conversation after its ids", async () => {
    const calls: string[] = [];

    await stream(
      [
        {
          conversation_id: "conv-2",
          conversation_description: "Trip",
          user_message_id: "u-1",
          bot_message_id: "b-1",
        },
      ],
      {
        onMessageIds: (userId, botId) => calls.push(`ids:${userId}:${botId}`),
        onConversationCreated: (id, description) =>
          calls.push(`created:${id}:${description}`),
      },
    );

    expect(calls).toEqual(["ids:u-1:b-1", "created:conv-2:Trip"]);
  });
});

describe("fetchChatStream — emoji acks", () => {
  it("passes the ack to the turn's event consumer", async () => {
    const events: ChatStreamEvent[] = [];

    await stream(
      [{ emoji_ack: { emoji: "👍", reacts_to_message_id: "u-1" } }],
      { onStreamEvent: (event) => events.push(event) },
    );

    expect(events).toEqual([
      { type: "emoji_ack", emoji: "👍", reactsToMessageId: "u-1" },
    ]);
  });
});
