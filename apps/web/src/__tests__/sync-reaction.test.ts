import { describe, expect, it, vi } from "vitest";
import { mapStoredMessageToConversationMessage } from "@/features/chat/hooks/useConversation";
import { db } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";

const SYNCED_AT = "2026-01-01T00:00:00Z";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {},
  toClientMessages: (messages: unknown[]) => messages,
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putConversation: vi.fn(),
    getMessagesForConversation: vi.fn().mockResolvedValue([]),
    syncMessages: vi.fn(),
  },
}));

vi.mock("@/stores/streamStore", () => ({
  hasAnyLiveTurn: () => false,
  isConversationStreamingNow: () => false,
  shouldBlockSyncForConversation: () => false,
}));

describe("syncing a conversation GAIA reacted in", () => {
  it("stores the reaction on the user's message, so a reload shows the badge", async () => {
    await applySyncedConversation("conv-1", {
      conversation_id: "conv-1",
      description: "Flights",
      messages: [
        {
          type: "user",
          response: "find my flight email",
          message_id: "user-1",
          seq: 1,
          date: SYNCED_AT,
          reaction: { emoji: "🔎", by: "jev" },
        },
      ],
      artifacts: [],
      has_live_approval: null,
      todo_id: null,
      source: null,
      starred: null,
      is_system_generated: null,
      system_purpose: null,
      is_unread: null,
      createdAt: SYNCED_AT,
      updatedAt: null,
    });

    const [, stored] = vi.mocked(db.syncMessages).mock.calls[0];
    expect(stored).toEqual([
      expect.objectContaining({
        id: "user-1",
        reaction: { emoji: "🔎", by: "jev" },
      }),
    ]);
    // The bubble reads the reaction off the message the list renders from the store.
    expect(mapStoredMessageToConversationMessage(stored[0]).reaction).toEqual({
      emoji: "🔎",
      by: "jev",
    });
  });
});
