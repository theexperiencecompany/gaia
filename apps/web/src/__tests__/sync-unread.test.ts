import type { ConversationSyncRow } from "@shared/api/generated";
import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { markAsRead: vi.fn().mockResolvedValue(undefined) },
}));

vi.mock("@/features/chat/live/connection", () => ({
  applyConversationPage: vi.fn(),
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putConversation: vi.fn(),
  },
}));

const AT = "2026-01-01T00:00:00Z";

/** A conversation the server marked unread because a notice landed in it. */
const noticedRow = (conversationId: string): ConversationSyncRow => ({
  conversation_id: conversationId,
  description: "Reminder",
  createdAt: AT,
  updatedAt: AT,
  items: [],
  state: { kind: "state", head: 0, display: "idle", work: [] },
  cursor: null,
  artifacts: [],
  awaiting_approval: false,
  has_older: false,
  is_system_generated: false,
  is_unread: true,
  source: null,
  starred: false,
  system_purpose: null,
  todo_id: null,
  listed: true,
});

afterEach(() => {
  vi.clearAllMocks();
  useChatStore.getState().setActiveConversationId(null);
});

describe("a conversation the server marked unread", () => {
  it("lights the dot when the user is elsewhere", async () => {
    useChatStore.getState().setActiveConversationId("other");

    await applySyncedConversation("c1", noticedRow("c1"));

    expect(vi.mocked(db.putConversation).mock.calls[0][0].isUnread).toBe(true);
    expect(chatApi.markAsRead).not.toHaveBeenCalled();
  });

  it("is read at once when it is the conversation on screen", async () => {
    useChatStore.getState().setActiveConversationId("c1");

    await applySyncedConversation("c1", noticedRow("c1"));

    expect(vi.mocked(db.putConversation).mock.calls[0][0].isUnread).toBe(false);
    expect(chatApi.markAsRead).toHaveBeenCalledWith("c1");
  });
});
