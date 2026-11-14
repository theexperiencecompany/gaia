// @vitest-environment jsdom

import { ApiError } from "@shared/api";
import type { ScreenItem } from "@shared/conversation";
import { replyItem, userItem } from "@shared/conversation/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChatStore } from "@/stores/chatStore";

/**
 * A fake events endpoint: each subscription is a stream the test feeds frames to
 * and then ends, drops, or refuses with 404.
 */
interface OpenStream {
  conversationId: string;
  push: (frame: unknown) => void;
  end: () => void;
  drop: (error: Error) => void;
  aborted: () => boolean;
}

const { server, saved, sendResult, retitled } = vi.hoisted(() => ({
  server: {
    streams: [] as OpenStream[],
    notFound: new Set<string>(),
  },
  saved: new Map<string, unknown>(),
  retitled: [] as { id: string; fields: unknown }[],
  sendResult: {
    fail: null as Error | null,
    refusals: [] as Error[],
    calls: [] as unknown[],
  },
}));

vi.mock("@/features/chat/api/chatApi", () => {
  class ConversationNotFoundError extends Error {}
  return {
    ConversationNotFoundError,
    chatApi: {
      subscribeToConversationEvents: (
        conversationId: string,
        onData: (raw: string) => void,
        signal: AbortSignal,
      ) =>
        new Promise<void>((resolve, reject) => {
          if (server.notFound.has(conversationId)) {
            reject(new ConversationNotFoundError(conversationId));
            return;
          }
          signal.addEventListener("abort", () => resolve());
          server.streams.push({
            conversationId,
            push: (frame) => onData(JSON.stringify({ frame })),
            end: resolve,
            drop: reject,
            aborted: () => signal.aborted,
          });
        }),
      sendConversationMessage: async (
        conversationId: string,
        body: { message_id: string },
      ) => {
        sendResult.calls.push({ conversationId, body });
        const refusal = sendResult.refusals.shift();
        if (refusal) throw refusal;
        if (sendResult.fail) throw sendResult.fail;
        return {
          conversation_id: conversationId,
          message_id: body.message_id,
          seq: 1,
        };
      },
    },
  };
});

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getConversationLog: async (id: string) => saved.get(id),
    putConversationLog: async (log: { conversationId: string }) => {
      saved.set(log.conversationId, structuredClone(log));
    },
    putConversation: async () => "",
    deleteConversationAndLog: async () => undefined,
    getAllConversations: async () => [],
    updateConversationFields: async (id: string, fields: unknown) => {
      retitled.push({ id, fields });
    },
  },
}));

import {
  deliverSend,
  openConversation,
  persistConversation,
} from "./connection";
import {
  liveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";
import { sendMessage } from "./sendMessage";

const AT = "2026-11-12T10:00:00+00:00";
const CONVERSATION = "conv-1";

const insert = (item: ScreenItem) => ({ kind: "screen_insert", item });
const screenOf = (...items: ScreenItem[]) => ({ kind: "screen", items });
const ids = () => view().items.map((item) => item.id);
const state = (head: number, display: string) => ({
  kind: "state",
  head,
  display,
  work: [],
});
const replyText = (attemptId: string, index: number, text: string) => ({
  kind: "reply_delta",
  attempt_id: attemptId,
  reply_id: null,
  index,
  payload: { type: "bubble_text", bubble: 0, text },
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const lastStream = () => server.streams.at(-1) as OpenStream;
const view = () => liveConversation(CONVERSATION).view;

let release: (() => void) | null = null;

beforeEach(() => {
  server.streams = [];
  server.notFound.clear();
  saved.clear();
  sendResult.fail = null;
  sendResult.refusals = [];
  sendResult.calls = [];
  retitled.length = 0;
  useLiveConversationStore.setState({ conversations: {} });
});

afterEach(() => {
  release?.();
  release = null;
  vi.useRealTimers();
});

describe("following a conversation's events", () => {
  it("takes the screen it opens on, then its patches and live deltas", async () => {
    release = openConversation(CONVERSATION);
    await flush();

    lastStream().push(screenOf(userItem("m1", 1, "hi")));
    lastStream().push(state(1, "thinking"));
    lastStream().push(insert(replyItem("r1", 2, "Hel")));
    lastStream().push(replyText("a1", 0, "Hel"));
    lastStream().push(replyText("a1", 1, "lo"));

    expect(ids()).toEqual(["m1", "r1"]);
    expect(view().display).toBe("thinking");
    expect(view().drafts[0]?.content.bubbles).toEqual(["Hello"]);
  });

  it("titles the conversation from its title update, leaving the view as it was", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(insert(userItem("m1", 1, "plan q3")));
    const before = view();

    lastStream().push({
      kind: "conversation_updated",
      description: "Q3 planning",
    });

    expect(retitled).toEqual([
      {
        id: CONVERSATION,
        fields: { description: "Q3 planning", title: "Q3 planning" },
      },
    ]);
    expect(view()).toBe(before);
  });

  it("reconnects after a dropped socket and takes the fresh screen it opens on", async () => {
    vi.useFakeTimers();
    release = openConversation(CONVERSATION);
    await vi.advanceTimersByTimeAsync(0);
    lastStream().push(insert(userItem("m1", 1)));
    lastStream().drop(new Error("socket lost"));

    await vi.advanceTimersByTimeAsync(1_000);

    expect(server.streams).toHaveLength(2);
    lastStream().push(
      screenOf(userItem("m1", 1), replyItem("r1", 2, "done", "answered")),
    );
    expect(ids()).toEqual(["m1", "r1"]);
  });

  it("reopens when a delta skips an index, and the fresh stream fills the gap", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const first = lastStream();
    first.push(insert(userItem("m1", 1)));
    first.push(replyText("a1", 0, "one "));
    first.push(replyText("a1", 2, "three"));
    await flush();

    expect(first.aborted()).toBe(true);
    const replay = lastStream();
    expect(server.streams).toHaveLength(2);
    replay.push(screenOf(userItem("m1", 1)));
    replay.push(replyText("a1", 1, "two "));
    replay.push(replyText("a1", 2, "three"));
    expect(view().drafts[0]?.content.bubbles).toEqual(["one two three"]);
  });

  it("waits on a conversation the server does not have yet and connects once a send lands", async () => {
    server.notFound.add(CONVERSATION);
    release = openConversation(CONVERSATION);
    await flush();
    expect(server.streams).toHaveLength(0);

    server.notFound.delete(CONVERSATION);
    await sendMessage("hello", { conversationId: CONVERSATION });
    await flush();

    expect(server.streams).toHaveLength(1);
  });

  it("stops reading when the last holder releases the conversation", async () => {
    release = openConversation(CONVERSATION);
    const second = openConversation(CONVERSATION);
    await flush();
    release();
    release = null;
    expect(lastStream().aborted()).toBe(false);
    second();
    expect(lastStream().aborted()).toBe(true);
  });
});

describe("sending", () => {
  it("sends the picked tool, workflow, calendar event and quoted message with the text", async () => {
    const workflow = {
      id: "w1",
      title: "Weekly digest",
      description: "Digest the week",
      steps: [{ id: "s1", title: "Read", description: "r", category: "gmail" }],
    };
    const event = {
      id: "e1",
      summary: "Standup",
      description: "",
      start: { dateTime: AT },
      end: { dateTime: AT },
    };
    const quoted = { id: "m0", content: "earlier", role: "assistant" as const };

    await sendMessage("run it", {
      conversationId: CONVERSATION,
      selected_tool: "gmail_send",
      tool_category: "gmail",
      selected_workflow: workflow,
      selected_calendar_event: event,
      reply_to_message: quoted,
    });

    const [call] = sendResult.calls as { body: Record<string, unknown> }[];
    expect(call.body).toMatchObject({
      text: "run it",
      selected_tool: "gmail_send",
      tool_category: "gmail",
      selected_workflow: workflow,
      selected_calendar_event: event,
      reply_to: "m0",
      reply_to_message: quoted,
    });
  });

  it("sends a workflow picked with no text", async () => {
    await sendMessage("", {
      conversationId: CONVERSATION,
      selected_workflow: {
        id: "w1",
        title: "Digest",
        description: "",
        steps: [],
      },
    });
    expect(sendResult.calls).toHaveLength(1);
  });

  it("shows the message at once and hands it to the server's item with the same id", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const sending = sendMessage("hello", { conversationId: CONVERSATION });
    const pending = view().pending;
    expect(pending).toHaveLength(1);
    await sending;

    lastStream().push(insert(userItem(pending[0].id, 1, "hello")));

    expect(view().pending).toEqual([]);
    expect(ids()).toEqual([pending[0].id]);
  });

  it("marks a send the server refused as failed, and a retry resends the same message", async () => {
    sendResult.fail = new Error("offline");
    await expect(
      sendMessage("hello", { conversationId: CONVERSATION }),
    ).rejects.toThrow("offline");
    const [{ id }] = view().pending;
    expect(liveConversation(CONVERSATION).sends[id].failed).toBe(true);

    sendResult.fail = null;
    await deliverSend(CONVERSATION, id);

    expect(liveConversation(CONVERSATION).sends[id].failed).toBe(false);
    const bodies = sendResult.calls.map(
      (call) => (call as { body: { message_id: string } }).body.message_id,
    );
    expect(bodies).toEqual([id, id]);
  });

  it("starts a new conversation under an id the client minted", async () => {
    await sendMessage("hello", { conversationId: null });
    const [call] = sendResult.calls as {
      conversationId: string;
      body: { text: string };
    }[];
    expect(call.conversationId).toMatch(/^[0-9a-f-]{36}$/);
    expect(call.body.text).toBe("hello");
  });

  it("starts the conversation over under a fresh id when its minted id is taken", async () => {
    sendResult.refusals = [
      ApiError.fromBody(409, {
        message: "That conversation id is taken.",
        code: "conversation_id_taken",
      }),
    ];
    await sendMessage("hello", { conversationId: null });
    const calls = sendResult.calls as {
      conversationId: string;
      body: { text: string };
    }[];
    expect(calls).toHaveLength(2);
    expect(calls[1].conversationId).not.toBe(calls[0].conversationId);
    expect(calls[1].body.text).toBe("hello");
    expect(liveConversation(calls[0].conversationId).sends).toEqual({});
    expect(useChatStore.getState().activeConversationId).toBe(
      calls[1].conversationId,
    );
  });

  it("marks the send failed when the fresh id is taken too", async () => {
    const taken = () =>
      ApiError.fromBody(409, {
        message: "That conversation id is taken.",
        code: "conversation_id_taken",
      });
    sendResult.refusals = [taken(), taken()];
    await expect(
      sendMessage("hello", { conversationId: null }),
    ).rejects.toThrow();
    const calls = sendResult.calls as { conversationId: string }[];
    expect(calls).toHaveLength(2);
    const [{ id }] = liveConversation(calls[1].conversationId).view.pending;
    expect(liveConversation(calls[1].conversationId).sends[id].failed).toBe(
      true,
    );
  });
});

describe("reload", () => {
  it("shows the saved screen before the stream reconnects, and resends what never landed", async () => {
    saved.set(CONVERSATION, {
      conversationId: CONVERSATION,
      items: [
        userItem("m1", 1, "first"),
        replyItem("r1", 2, "answer", "answered"),
      ],
      head: 3,
      sends: {
        "m-unsent": {
          body: { message_id: "m-unsent", text: "second" },
          fileData: [],
          failed: false,
        },
      },
    });

    release = openConversation(CONVERSATION);
    await flush();

    expect(ids()).toEqual(["m1", "r1"]);
    expect(view().head).toBe(3);
    expect(view().pending.map((pending) => pending.id)).toEqual(["m-unsent"]);
    expect(sendResult.calls).toHaveLength(1);

    // A reply mid-stream at reload: its draft is rebuilt from the stream's replay.
    lastStream().push(insert(userItem("m-unsent", 4, "second")));
    lastStream().push(replyText("a2", 0, "on it"));
    expect(view().pending).toEqual([]);
    expect(view().drafts[0]?.content.bubbles).toEqual(["on it"]);
  });

  it("saves the screen and the sends it holds", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(insert(userItem("m1", 1)));
    persistConversation(CONVERSATION, { immediately: true });
    await flush();

    expect(
      (saved.get(CONVERSATION) as { items: ScreenItem[] }).items,
    ).toHaveLength(1);
  });
});
