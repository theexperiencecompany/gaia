/**
 * Steering: a send landing while its conversation streams starts immediately
 * instead of queueing client-side.
 *
 * The backend folds same-conversation work into the live run's next reasoning
 * step, so holding the send until the turn ends only guaranteed it would start
 * a whole separate run. These tests pin the routing: mid-turn sends on a
 * resolved conversation become steering sessions (own key, no shared-slot
 * ownership); sends against a not-yet-created conversation still queue.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    putMessage: vi.fn().mockResolvedValue(undefined),
    getMessagesForConversation: vi.fn().mockResolvedValue([]),
    updateMessage: vi.fn().mockResolvedValue(undefined),
    updateMessageStatus: vi.fn().mockResolvedValue(undefined),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/stores/chatStore", () => ({
  useChatStore: Object.assign(vi.fn(), { getState: vi.fn() }),
}));

vi.mock("@/stores/streamStore", () => ({
  PENDING_KEY_PREFIX: "pending:",
}));

type FakeSession = {
  key: string;
  boundConversationId: string | null;
  isSteering: boolean;
  end: () => void;
  start: () => Promise<void>;
  abort: () => Promise<void>;
};

const constructed: Array<{ key: string; options?: { steering?: boolean } }> =
  [];
const started: string[] = [];
const aborted: string[] = [];
const sessions: FakeSession[] = [];

vi.mock("@/features/chat/stream/turnSession", () => ({
  TurnSession: vi.fn().mockImplementation(function (
    this: unknown,
    key: string,
    _args: unknown,
    callbacks: { onEnd: (session: unknown) => void },
    options?: { steering?: boolean },
  ) {
    constructed.push({ key, options });
    // Production sessions report the conversation they write into, which is
    // how stop() finds steers filed under distinct keys.
    const args = _args as { options?: { conversationId?: string | null } };
    const boundConversationId = args?.options?.conversationId ?? null;
    const session: FakeSession = {
      key,
      boundConversationId,
      isSteering: options?.steering ?? false,
      // The manager only learns a turn is over through this callback, so a
      // fake that never fires it cannot exercise teardown at all.
      end: () => callbacks.onEnd(session),
      start: vi.fn().mockImplementation(async () => {
        started.push(key);
      }),
      abort: vi.fn().mockImplementation(async () => {
        aborted.push(key);
      }),
    };
    sessions.push(session);
    return session;
  }),
}));

import { turnManager } from "@/features/chat/stream/turnManager";
import type { SendArgs } from "@/features/chat/stream/types";

const CONV = "conv-steer-1";

const sendArgs = (text: string, conversationId: string | null): SendArgs => ({
  inputText: text,
  userMessage: {
    type: "user",
    response: text,
    date: new Date().toISOString(),
    message_id: `msg-${text}`,
  },
  options: {
    fileData: [],
    selectedTool: null,
    toolCategory: null,
    selectedWorkflow: null,
    selectedCalendarEvent: null,
    optimisticUserId: `opt-${text}`,
    replyToMessage: null,
    conversationId,
    isOnboardingDemo: false,
  },
});

const resetManager = () => {
  constructed.length = 0;
  started.length = 0;
  aborted.length = 0;
  sessions.length = 0;
  const manager = turnManager as unknown as {
    sessions: Map<string, unknown>;
    queues: Map<string, unknown[]>;
    pendingKey: string | null;
  };
  manager.sessions.clear();
  manager.queues.clear();
  manager.pendingKey = null;
};

describe("turnManager steering", () => {
  beforeEach(resetManager);

  it("starts a steering session instead of queueing mid-turn", () => {
    turnManager.send(sendArgs("first", CONV));
    turnManager.send(sendArgs("second", CONV));

    expect(constructed).toHaveLength(2);
    expect(constructed[0]).toMatchObject({ key: CONV });
    expect(constructed[1].key).toContain(`${CONV}:steer:`);
    expect(constructed[1].options).toMatchObject({ steering: true });
    expect(started).toHaveLength(2);
    const manager = turnManager as unknown as {
      queues: Map<string, unknown[]>;
    };
    expect(manager.queues.size).toBe(0);
  });

  it("still queues sends against a not-yet-created conversation", () => {
    turnManager.send(sendArgs("first", null));
    // Null resolves to a pending key; the pending session counts as active,
    // but with no conversation id the backend has nothing to fold into.
    turnManager.send(sendArgs("second", null));

    expect(constructed).toHaveLength(1);
    const manager = turnManager as unknown as {
      queues: Map<string, unknown[]>;
    };
    expect(manager.queues.size).toBe(1);
  });

  it("stop aborts the main turn and every steer", async () => {
    turnManager.send(sendArgs("first", CONV));
    turnManager.send(sendArgs("second", CONV));
    turnManager.send(sendArgs("third", CONV));

    await expect(turnManager.stop(CONV)).resolves.toBe(true);
    expect(aborted).toHaveLength(3);
  });

  it("stop returns false with nothing live", async () => {
    await expect(turnManager.stop(CONV)).resolves.toBe(false);
  });

  it("a finished steer leaves the main turn live and stoppable", async () => {
    turnManager.send(sendArgs("first", CONV));
    turnManager.send(sendArgs("second", CONV));
    const [main, steer] = sessions;

    // A steer is short-lived and normally ends first. Teardown keyed on the
    // conversation id evicted the main turn with it, so Stop silently did
    // nothing while the run was still streaming.
    steer.end();

    expect(turnManager.isTurnActive(CONV)).toBe(true);
    await expect(turnManager.stop(CONV)).resolves.toBe(true);
    expect(aborted).toEqual([main.key]);
  });

  it("a finished steer does not dispatch the conversation's queue", () => {
    turnManager.send(sendArgs("first", CONV));
    const manager = turnManager as unknown as {
      queues: Map<string, SendArgs[]>;
    };
    manager.queues.set(CONV, [sendArgs("held", CONV)]);
    turnManager.send(sendArgs("second", CONV));

    sessions[1].end();

    expect(manager.queues.get(CONV)).toHaveLength(1);
    expect(constructed).toHaveLength(2);
  });

  it("the main turn ending still dispatches its queue", () => {
    turnManager.send(sendArgs("first", CONV));
    const manager = turnManager as unknown as {
      queues: Map<string, SendArgs[]>;
    };
    manager.queues.set(CONV, [sendArgs("held", CONV)]);

    sessions[0].end();

    expect(manager.queues.has(CONV)).toBe(false);
    expect(constructed).toHaveLength(2);
  });
});
