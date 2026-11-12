import { afterEach, describe, expect, it, vi } from "vitest";
import { db, type IMessage } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {},
  toClientMessages: (messages: unknown[]) => messages,
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putConversation: vi.fn(),
    getMessagesForConversation: vi.fn(),
    syncMessages: vi.fn(),
  },
}));

vi.mock("@/stores/streamStore", () => ({
  hasAnyLiveTurn: () => false,
  isConversationStreamingNow: () => false,
  shouldBlockSyncForConversation: () => false,
}));

const SENT = new Date("2026-01-01T00:00:00Z");

function cachedWithoutServerId(content: string, createdAt: Date): IMessage {
  return {
    id: `c1-0-${createdAt.getTime()}`,
    conversationId: "c1",
    content,
    role: "user",
    status: "sent",
    createdAt,
    updatedAt: createdAt,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("syncing a conversation whose old messages just got real ids", () => {
  it("replaces the cached copy instead of showing the message twice", async () => {
    const older = new Date("2025-12-01T00:00:00Z");
    vi.mocked(db.getMessagesForConversation).mockResolvedValue([
      cachedWithoutServerId("hello", SENT),
      cachedWithoutServerId("outside the window", older),
    ]);

    await applySyncedConversation("c1", {
      conversation_id: "c1",
      description: "chat",
      createdAt: SENT.toISOString(),
      updatedAt: SENT.toISOString(),
      messages: [
        {
          type: "user",
          response: "hello",
          date: SENT.toISOString(),
          message_id: "6af6468dc9beb9308070244d",
        },
      ],
      artifacts: [],
    } as unknown as Parameters<typeof applySyncedConversation>[1]);

    const [, merged] = vi.mocked(db.syncMessages).mock.calls[0];
    expect(merged.map((m) => [m.id, m.content])).toEqual([
      [`c1-0-${older.getTime()}`, "outside the window"],
      ["6af6468dc9beb9308070244d", "hello"],
    ]);
  });
});
