// @vitest-environment jsdom
import type { Entry, LoggedEntry } from "@shared/conversation";
import { reply, replySettled, userMessage } from "@shared/conversation/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A fake events endpoint: each subscription is a stream the test feeds frames to
 * and then ends, drops, or refuses with 404, recording the `after` it opened with.
 */
interface OpenStream {
  conversationId: string;
  after: number;
  push: (frame: unknown, streamId?: string | null) => void;
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
  sendResult: { fail: null as Error | null, calls: [] as unknown[] },
}));

vi.mock("@/features/chat/api/chatApi", () => {
  class ConversationNotFoundError extends Error {}
  return {
    ConversationNotFoundError,
    chatApi: {
      subscribeToConversationEvents: (
        conversationId: string,
        after: number,
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
            after,
            push: (frame, streamId = null) =>
              onData(JSON.stringify({ stream_id: streamId, frame })),
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

const entry = (seq: number, logged: Entry) => ({
  kind: "entry",
  seq,
  at: AT,
  entry: logged,
});
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
  payload: { type: "response", response: text },
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
  it("folds every frame into the view, from the log's start for a conversation never seen", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    expect(lastStream().after).toBe(0);

    lastStream().push(entry(1, userMessage("m1", "hi")));
    lastStream().push(state(1, "thinking"));
    lastStream().push(replyText("a1", 0, "Hel"));
    lastStream().push(replyText("a1", 1, "lo"));

    expect(view().entries.map((logged) => logged.seq)).toEqual([1]);
    expect(view().display).toBe("thinking");
    expect(view().drafts[0]?.content.responseText).toBe("Hello");
  });

  it("titles the conversation from its title update, leaving the view as it was", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1", "plan q3")));
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

  it("reconnects after a dropped socket from before what can still change, not from the start", async () => {
    vi.useFakeTimers();
    release = openConversation(CONVERSATION);
    await vi.advanceTimersByTimeAsync(0);
    const first = lastStream();
    first.push(entry(1, userMessage("m1")));
    first.push(entry(2, reply("r1", "a1")));
    first.push(entry(3, replySettled("r1", ["m1"], 1)));
    first.push(entry(4, userMessage("m2")));
    first.drop(new Error("socket lost"));

    await vi.advanceTimersByTimeAsync(1_000);

    expect(server.streams).toHaveLength(2);
    // m2 has no settled reply yet, so its reaction may still land in place.
    expect(lastStream().after).toBe(3);
  });

  it("reopens from the log when a delta skips an index, and the replay fills the gap", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const first = lastStream();
    first.push(entry(1, userMessage("m1")));
    first.push(replyText("a1", 0, "one "));
    first.push(replyText("a1", 2, "three"));
    await flush();

    expect(first.aborted()).toBe(true);
    const replay = lastStream();
    expect(server.streams).toHaveLength(2);
    expect(replay.after).toBe(0);
    replay.push(entry(1, userMessage("m1")));
    replay.push(replyText("a1", 0, "one "));
    replay.push(replyText("a1", 1, "two "));
    replay.push(replyText("a1", 2, "three"));
    expect(view().drafts[0]?.content.responseText).toBe("one two three");
  });

  it("reopens before an entry it never held when that entry is updated in place", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const first = lastStream();
    first.push(entry(1, userMessage("m1")));
    first.push(entry(2, reply("r1", "a1")));
    first.push(entry(3, replySettled("r1", ["m1"], 1)));
    first.push(entry(5, userMessage("m3")));
    first.push({
      kind: "entry_updated",
      seq: 4,
      entry: userMessage("m2", "text", { emoji: "👍", by: "jev" }, 1),
    });
    await flush();

    expect(lastStream().after).toBe(3);
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
      selectedTool: "gmail_send",
      toolCategory: "gmail",
      selectedWorkflow: workflow,
      selectedCalendarEvent: event,
      replyToMessage: quoted,
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
      selectedWorkflow: {
        id: "w1",
        title: "Digest",
        description: "",
        steps: [],
      },
    });
    expect(sendResult.calls).toHaveLength(1);
  });

  it("shows the message at once and hands it to the log entry with the same id", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const sending = sendMessage("hello", { conversationId: CONVERSATION });
    const pending = view().pending;
    expect(pending).toHaveLength(1);
    await sending;

    lastStream().push(entry(1, userMessage(pending[0].id, "hello")));

    expect(view().pending).toEqual([]);
    expect(view().entries[0].entry.id).toBe(pending[0].id);
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
});

describe("reload", () => {
  it("shows the saved log before the stream reconnects, resumes after it, and resends what never landed", async () => {
    const savedEntries: LoggedEntry[] = [
      { seq: 1, at: AT, entry: userMessage("m1", "first") },
      { seq: 2, at: AT, entry: reply("r1", "a1", "answer", 1) },
      { seq: 3, at: AT, entry: replySettled("r1", ["m1"], 1) },
    ];
    saved.set(CONVERSATION, {
      conversationId: CONVERSATION,
      entries: savedEntries,
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

    expect(view().entries.map((logged) => logged.seq)).toEqual([1, 2, 3]);
    expect(view().pending.map((pending) => pending.id)).toEqual(["m-unsent"]);
    expect(lastStream().after).toBe(3);
    expect(sendResult.calls).toHaveLength(1);

    // A reply mid-stream at reload: its draft is rebuilt from the stream's replay.
    lastStream().push(entry(4, userMessage("m-unsent", "second")));
    lastStream().push(replyText("a2", 0, "on it"));
    expect(view().pending).toEqual([]);
    expect(view().drafts[0]?.content.responseText).toBe("on it");
  });

  it("saves the log and the sends it holds", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1")));
    persistConversation(CONVERSATION, { immediately: true });
    await flush();

    expect(
      (saved.get(CONVERSATION) as { entries: LoggedEntry[] }).entries,
    ).toHaveLength(1);
  });
});
