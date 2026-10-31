import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import { db, type IConversation } from "@/lib/db/chatDb";
import {
  applySyncedConversation,
  batchSyncConversations,
} from "@/services/syncService";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { fetchConversations: vi.fn(), batchSyncConversations: vi.fn() },
  toClientMessages: () => [],
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getAllConversations: vi.fn(),
    deleteConversationsAndMessagesBulk: vi.fn(),
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

const LONG_AGO = new Date("2026-01-01T00:00:00Z");

const LISTED = {
  conversation_id: "listed",
  user_id: "u1",
  description: "listed",
  starred: null,
  is_system_generated: null,
  system_purpose: null,
  is_unread: null,
  source: null,
  has_live_approval: null,
  createdAt: LONG_AGO.toISOString(),
  updatedAt: LONG_AGO.toISOString(),
};

function listing(conversations: (typeof LISTED)[]) {
  return {
    conversations,
    total: conversations.length,
    page: 1,
    limit: 50,
    total_pages: 1,
  };
}

function local(id: string, overrides: Partial<IConversation> = {}) {
  return {
    id,
    title: id,
    createdAt: LONG_AGO,
    updatedAt: LONG_AGO,
    ...overrides,
  } satisfies IConversation;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("syncing a tracked todo's chat", () => {
  it("keeps it locally although the server never lists it", async () => {
    vi.mocked(chatApi.fetchConversations).mockResolvedValue({
      conversations: [
        {
          conversation_id: "listed",
          user_id: "u1",
          description: "listed",
          starred: null,
          is_system_generated: null,
          system_purpose: null,
          is_unread: null,
          source: null,
          has_live_approval: null,
          createdAt: LONG_AGO.toISOString(),
          updatedAt: LONG_AGO.toISOString(),
        },
      ],
      total: 1,
      page: 1,
      limit: 50,
      total_pages: 1,
    });
    vi.mocked(db.getAllConversations).mockResolvedValue([
      local("listed"),
      local("deleted-on-server"),
      local("todo-chat", { todoId: "todo-1" }),
    ]);

    await batchSyncConversations();

    expect(db.deleteConversationsAndMessagesBulk).toHaveBeenCalledWith([
      "deleted-on-server",
    ]);
  });

  it("asks the server about every local todo chat and drops the ones it no longer has", async () => {
    vi.mocked(chatApi.fetchConversations).mockResolvedValue(listing([]));
    vi.mocked(db.getAllConversations).mockResolvedValue([
      local("kept-todo-chat", { todoId: "todo-1" }),
      local("deleted-todo-chat", { todoId: "todo-2" }),
    ]);
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: [],
      missing: ["deleted-todo-chat"],
    });

    await batchSyncConversations();

    expect(chatApi.batchSyncConversations).toHaveBeenCalledWith(
      [
        {
          conversation_id: "kept-todo-chat",
          last_updated: LONG_AGO.toISOString(),
        },
        {
          conversation_id: "deleted-todo-chat",
          last_updated: LONG_AGO.toISOString(),
        },
      ],
      {},
    );
    expect(db.deleteConversationsAndMessagesBulk).toHaveBeenCalledWith([
      "deleted-todo-chat",
    ]);
  });

  it("stores which todo the chat belongs to", async () => {
    await applySyncedConversation("todo-chat", {
      conversation_id: "todo-chat",
      description: "Watch the deploy",
      messages: [],
      artifacts: [],
      active_stream_id: null,
      has_live_approval: null,
      todo_id: "todo-1",
      starred: null,
      is_system_generated: null,
      system_purpose: null,
      is_unread: null,
      createdAt: LONG_AGO.toISOString(),
      updatedAt: null,
    });

    expect(vi.mocked(db.putConversation).mock.calls[0][0]).toMatchObject({
      id: "todo-chat",
      title: "Watch the deploy",
      todoId: "todo-1",
    });
  });
});
