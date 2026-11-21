// @vitest-environment jsdom

/**
 * Message order is the server's seq on every path that puts a message in front
 * of the user: the store, a sync merge, and the live turn. A date never orders.
 */
import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getAllConversations: vi.fn().mockResolvedValue([]),
    getAllMessages: vi.fn().mockResolvedValue([]),
    getMessagesForConversation: vi.fn().mockResolvedValue([]),
    putConversation: vi.fn().mockResolvedValue(undefined),
    putMessage: vi.fn().mockResolvedValue(undefined),
    syncMessages: vi.fn().mockResolvedValue(undefined),
    updateMessage: vi.fn().mockResolvedValue(undefined),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/stores/streamStore", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/stores/streamStore")>()),
  shouldBlockSyncForConversation: () => false,
  isConversationStreamingNow: () => false,
}));

import { textSendArgs } from "@/__tests__/helpers/sendArgs";
import type { SyncedConversation } from "@/features/chat/api/chatApi";
import { turnManager } from "@/features/chat/stream/turnManager";
import { TurnSession } from "@/features/chat/stream/turnSession";
import type { SendArgs } from "@/features/chat/stream/types";
import { db, type IMessage } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";

const CONV = "conv-order";

const record = (
  id: string,
  createdAt: string,
  overrides: Partial<IMessage> = {},
): IMessage => ({
  id,
  conversationId: CONV,
  content: id,
  role: "user",
  status: "sent",
  createdAt: new Date(createdAt),
  updatedAt: new Date(createdAt),
  messageId: id,
  ...overrides,
});

const shown = () =>
  (useChatStore.getState().messagesByConversation[CONV] ?? []).map((m) => m.id);

const serverMessage = (
  id: string,
  type: "user" | "bot",
  date: string,
  seq: number,
) => ({ type, response: id, message_id: id, date, seq });

const synced = (
  messages: ReturnType<typeof serverMessage>[],
): SyncedConversation =>
  ({
    conversation_id: CONV,
    description: "order",
    messages,
    artifacts: [],
  }) as unknown as SyncedConversation;

beforeEach(() => {
  vi.clearAllMocks();
  act(() => useChatStore.getState().setMessagesForConversation(CONV, []));
});

describe("a reply streaming while the user sends again", () => {
  it("stays above the message sent while it streamed, though it finished later", () => {
    const store = useChatStore.getState();
    act(() => {
      store.addOrUpdateMessage(record("a", "2026-01-01T09:00:00Z", { seq: 1 }));
      store.addOrUpdateMessage(
        record("reply", "2026-01-01T09:00:01Z", {
          role: "assistant",
          status: "sending",
        }),
      );
      store.updateMessageInPlace(
        record("reply", "2026-01-01T09:00:01Z", {
          role: "assistant",
          status: "sending",
          seq: 2,
        }),
      );
      store.addOrUpdateMessage(
        record("b", "2026-01-01T09:00:05Z", {
          optimistic: true,
          status: "sending",
        }),
      );
      store.addOrUpdateMessage(record("b", "2026-01-01T09:00:05Z", { seq: 3 }));
      // The server dates the reply when its turn finished, after B was sent.
      store.addOrUpdateMessage(
        record("reply", "2026-01-01T09:00:30Z", { role: "assistant", seq: 2 }),
      );
    });

    expect(shown()).toEqual(["a", "reply", "b"]);
  });

  it("keeps that order when a sync brings the server's copies", async () => {
    vi.mocked(db.getMessagesForConversation).mockResolvedValue([]);

    await applySyncedConversation(
      CONV,
      synced([
        serverMessage("a", "user", "2026-01-01T09:00:00Z", 1),
        serverMessage("reply", "bot", "2026-01-01T09:00:30Z", 2),
        serverMessage("b", "user", "2026-01-01T09:00:05Z", 3),
      ]),
    );

    const [, merged] = vi.mocked(db.syncMessages).mock.calls[0];
    expect(merged.map((m) => [m.id, m.seq])).toEqual([
      ["a", 1],
      ["reply", 2],
      ["b", 3],
    ]);
  });
});

describe("updating a message in place", () => {
  it("moves it to its place when its seq arrives", () => {
    const store = useChatStore.getState();
    act(() => {
      store.addOrUpdateMessage(record("a", "2026-01-01T09:00:00Z", { seq: 1 }));
      store.addOrUpdateMessage(
        record("reply", "2026-01-01T09:00:01Z", {
          role: "assistant",
          status: "sending",
        }),
      );
      store.addOrUpdateMessage(
        record("b", "2026-01-01T09:00:02Z", { status: "sending" }),
      );
      store.updateMessageInPlace(
        record("b", "2026-01-01T09:00:02Z", { status: "sending", seq: 2 }),
      );
    });

    expect(shown()).toEqual(["a", "b", "reply"]);
  });
});

describe("a conversation cached before messages had a seq", () => {
  it("keeps its cached history above a new message the server has placed", () => {
    const store = useChatStore.getState();
    act(() => {
      store.setMessagesForConversation(CONV, [
        record("old-1", "2026-01-01T08:00:00Z"),
        record("old-2", "2026-01-01T08:01:00Z", { role: "assistant" }),
      ]);
      // Sent before the next sync: the identity frame already placed it.
      store.addOrUpdateMessage(
        record("new", "2026-01-01T07:00:00Z", { seq: 9 }),
      );
    });

    expect(shown()).toEqual(["old-1", "old-2", "new"]);
  });

  it("merges a sync of seq'd copies with local sends the server has not placed", async () => {
    vi.mocked(db.getMessagesForConversation).mockResolvedValue([
      record("old-1", "2026-01-01T08:00:00Z"),
      record("old-2", "2026-01-01T08:01:00Z", { role: "assistant" }),
      record("unsent", "2026-01-01T07:00:00Z", {
        optimistic: true,
        status: "failed",
      }),
    ]);

    await applySyncedConversation(
      CONV,
      synced([
        serverMessage("old-1", "user", "2026-01-01T08:00:00Z", 1),
        serverMessage("old-2", "bot", "2026-01-01T08:01:00Z", 2),
        serverMessage("elsewhere", "user", "2026-01-01T06:00:00Z", 3),
      ]),
    );

    const [, merged] = vi.mocked(db.syncMessages).mock.calls[0];
    expect(merged.map((m) => m.id)).toEqual([
      "old-1",
      "old-2",
      "elsewhere",
      "unsent",
    ]);
  });
});

describe("the client never edits a time to order a message", () => {
  it("dates the reply's record when it is created, not from the user message", async () => {
    const args = textSendArgs(CONV, "hello");
    args.userMessage.date = "2020-01-01T00:00:00.000Z";
    const session = new TurnSession(CONV, args, {
      onEnd: vi.fn(),
      onRekey: vi.fn(),
    }) as unknown as {
      dispatchEvent: (event: Record<string, unknown>) => Promise<unknown>;
    };
    const before = Date.now();

    await act(async () => {
      await session.dispatchEvent({
        type: "conversation_initialized",
        user_message_id: "opt-1",
        user_message_seq: 5,
        bot_message_id: "bot-1",
      });
      await session.dispatchEvent({ type: "reply_placed", seq: 6 });
    });

    const reply = useChatStore
      .getState()
      .messagesByConversation[CONV]?.find((m) => m.id === "bot-1");
    expect(reply?.seq).toBe(6);
    expect(reply?.createdAt.getTime()).toBeGreaterThanOrEqual(before);
    expect(db.updateMessage).toHaveBeenCalledWith(
      "opt-1",
      expect.objectContaining({ seq: 5 }),
    );
  });

  it("dispatches a queued send without restamping it", () => {
    const queued: SendArgs = textSendArgs(CONV, "later");
    const sent = vi.spyOn(turnManager, "send").mockReturnValue(undefined);
    const manager = turnManager as unknown as {
      queues: Map<string, SendArgs[]>;
      dispatchQueued: (key: string) => void;
    };
    manager.queues.set(CONV, [queued]);

    manager.dispatchQueued(CONV);

    expect(db.updateMessage).toHaveBeenCalledWith("opt-1", {
      status: "sending",
    });
    expect(sent.mock.calls[0][0].userMessage.date).toBe(
      queued.userMessage.date,
    );
    sent.mockRestore();
  });
});
