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
  it("shows GAIA's stored reaction as a badge on the user's message", async () => {
    getMock.mockResolvedValueOnce(
      conversationDetail([
        apiMessage({
          message_id: "user-1",
          type: "user",
          response: "book it",
          reaction: { emoji: "👍", by: "chat_model" },
        }),
        apiMessage({ message_id: "bot-1", response: "booked" }),
      ]),
    );

    const messages = await fetchMessages("conv-1");

    const userMessage = messages.find((message) => message.id === "user-1");
    expect(userMessage?.reactions).toEqual([{ emoji: "👍", ackId: "user-1" }]);
    expect(
      messages.find((message) => message.id === "bot-1")?.reactions,
    ).toBeNull();
  });

  it("leaves a message without a stored reaction unbadged", async () => {
    getMock.mockResolvedValueOnce(
      conversationDetail([apiMessage({ message_id: "bot-1" })]),
    );

    const messages = await fetchMessages("conv-1");

    expect(messages).toHaveLength(1);
    expect(messages[0].reactions).toBeNull();
  });
});
