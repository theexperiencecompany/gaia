import type { ConversationEntry } from "@shared/api/generated";
import { afterEach, describe, expect, it, vi } from "vitest";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import {
  applyOlderMessagesPage,
  applySyncedConversation,
} from "@/services/syncService";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {},
  toClientMessages: (messages: unknown[]) => messages,
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getConversation: vi.fn(),
    putConversation: vi.fn(),
    getMessagesForConversation: vi.fn(),
    syncMessages: vi.fn(),
  },
}));

const BASE = Date.parse("2026-01-01T00:00:00Z");

const entry = (seq: number): ConversationEntry => ({
  type: seq % 2 === 0 ? "bot" : "user",
  response: `message ${seq}`,
  date: new Date(BASE + seq * 1000).toISOString(),
  message_id: `m${seq}`,
  seq,
});

const stored = (seq: number): IMessage => ({
  id: `m${seq}`,
  conversationId: "c1",
  content: `message ${seq}`,
  role: seq % 2 === 0 ? "assistant" : "user",
  status: "sent",
  createdAt: new Date(BASE + seq * 1000),
  updatedAt: new Date(BASE + seq * 1000),
  messageId: `m${seq}`,
  seq,
});

const range = <T>(from: number, to: number, make: (seq: number) => T): T[] =>
  Array.from({ length: to - from + 1 }, (_, i) => make(from + i));

const conversation: IConversation = {
  id: "c1",
  title: "chat",
  hasOlder: true,
  createdAt: new Date(BASE),
  updatedAt: new Date(BASE),
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("loading a conversation's older messages", () => {
  it("stores the page under the stored messages, in order, and records that none remain", async () => {
    vi.mocked(db.getMessagesForConversation).mockResolvedValue(
      range(51, 100, stored),
    );
    vi.mocked(db.getConversation).mockResolvedValue(conversation);

    await applyOlderMessagesPage("c1", {
      messages: range(1, 50, entry),
      has_more: false,
    });

    const [, merged] = vi.mocked(db.syncMessages).mock.calls[0];
    expect(merged.map((message) => message.seq)).toEqual(
      range(1, 100, (seq) => seq),
    );
    expect(vi.mocked(db.putConversation)).toHaveBeenCalledWith({
      ...conversation,
      hasOlder: false,
    });
  });

  it("keeps hasOlder set when the server says more remain", async () => {
    vi.mocked(db.getMessagesForConversation).mockResolvedValue(
      range(101, 120, stored),
    );
    vi.mocked(db.getConversation).mockResolvedValue(conversation);

    await applyOlderMessagesPage("c1", {
      messages: range(51, 100, entry),
      has_more: true,
    });

    expect(vi.mocked(db.putConversation).mock.calls[0][0].hasOlder).toBe(true);
  });

  it("stores has_older from a synced conversation row", async () => {
    vi.mocked(db.getMessagesForConversation).mockResolvedValue([]);

    await applySyncedConversation("c1", {
      conversation_id: "c1",
      description: "chat",
      createdAt: new Date(BASE).toISOString(),
      updatedAt: new Date(BASE).toISOString(),
      messages: range(1, 2, entry),
      artifacts: [],
      awaiting_approval: false,
      has_older: true,
      is_system_generated: false,
      is_unread: false,
      source: null,
      starred: false,
      system_purpose: null,
      todo_id: null,
    });

    expect(vi.mocked(db.putConversation).mock.calls[0][0].hasOlder).toBe(true);
  });
});
