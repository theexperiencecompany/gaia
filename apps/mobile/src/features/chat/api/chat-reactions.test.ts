import { describe, expect, it, vi } from "vitest";
import { fetchMessages } from "./chat-api";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("@/lib/api", () => ({
  apiService: { get: getMock },
}));

function conversationDetail(messages: unknown[]) {
  return {
    _id: "conv-1",
    user_id: "user-1",
    conversation_id: "conv-1",
    description: "Test",
    is_system_generated: false,
    system_purpose: null,
    is_unread: false,
    messages,
    createdAt: "2026-01-01T00:00:00.000Z",
  };
}

function apiMessage(overrides: Record<string, unknown>) {
  return {
    type: "bot",
    response: "hello",
    date: "2026-01-01T00:00:00.000Z",
    message_id: "msg-1",
    fileIds: [],
    fileData: [],
    ...overrides,
  };
}

describe("fetchMessages — reaction parity", () => {
  it("carries kind/reacts_to_message_id onto the normalized message", async () => {
    getMock.mockResolvedValueOnce(
      conversationDetail([
        apiMessage({ message_id: "user-1", type: "user", response: "book it" }),
        apiMessage({
          message_id: "ack-1",
          response: "👍",
          kind: "emoji_ack",
          reacts_to_message_id: "user-1",
        }),
      ]),
    );

    const messages = await fetchMessages("conv-1");

    const ack = messages.find((message) => message.id === "ack-1");
    expect(ack?.kind).toBe("emoji_ack");
    expect(ack?.reacts_to_message_id).toBe("user-1");
  });

  it("defaults the reaction fields to null when the backend omits them", async () => {
    getMock.mockResolvedValueOnce(
      conversationDetail([apiMessage({ message_id: "bot-1" })]),
    );

    const messages = await fetchMessages("conv-1");

    expect(messages).toHaveLength(1);
    expect(messages[0].kind).toBeNull();
    expect(messages[0].reacts_to_message_id).toBeNull();
  });
});
