import { ApiError } from "@gaia/shared";
import { sendingLoadingRow } from "@gaia/shared/conversation";
import {
  notice,
  reply,
  replySettled,
  todoWoke,
  toolCallCard,
  userMessage,
  workFinished,
  workflowFired,
  workStarted,
} from "@gaia/shared/conversation/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A fake events endpoint: each subscription is a stream the test feeds frames to
 * and then ends, drops, or refuses with 404, recording the `after` it opened with.
 */
interface OpenStream {
  after: number;
  push: (frame: unknown) => void;
  drop: (error: Error) => void;
  aborted: () => boolean;
}

const { server, sendResult, ids } = vi.hoisted(() => ({
  server: { streams: [] as OpenStream[], notFound: new Set<string>() },
  sendResult: {
    fail: null as Error | null,
    refusals: [] as Error[],
    calls: [] as { conversationId: string; body: { message_id: string } }[],
  },
  ids: { next: 0 },
}));

vi.mock("expo-crypto", () => ({
  randomUUID: () => {
    ids.next += 1;
    return `id-${ids.next}`;
  },
}));

vi.mock("@/lib/query-provider", () => ({
  queryClient: { setQueryData: vi.fn() },
}));

vi.mock("@/lib/sse-client", () => {
  class EventStreamHttpError extends Error {
    constructor(readonly status: number) {
      super(`HTTP ${status}`);
    }
  }
  return { EventStreamHttpError };
});

vi.mock("../api/queries", () => ({
  chatKeys: { conversations: () => ["chat", "conversations"] },
}));

vi.mock("../api/chat-api", async () => {
  const { EventStreamHttpError } = await import("@/lib/sse-client");
  return {
    chatApi: {
      subscribeToConversationEvents: (
        conversationId: string,
        after: number,
        onData: (raw: string) => void,
        signal: AbortSignal,
      ) =>
        new Promise<void>((resolve, reject) => {
          if (server.notFound.has(conversationId)) {
            reject(new EventStreamHttpError(404));
            return;
          }
          signal.addEventListener("abort", () => resolve());
          server.streams.push({
            after,
            push: (frame) => onData(JSON.stringify({ stream_id: null, frame })),
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
        return { conversation_id: conversationId, message_id: body.message_id };
      },
      retryConversationMessage: async (
        conversationId: string,
        body: { message_id: string },
      ) => {
        sendResult.calls.push({ conversationId, body });
        return { conversation_id: conversationId, message_id: body.message_id };
      },
    },
  };
});

import { usePaywallStore } from "@/stores/paywall-store";
import { openConversation } from "./connection";
import {
  liveConversation,
  useLiveConversationStore,
} from "./live-conversation-store";
import { liveMessages } from "./live-messages";
import { retryMessage, sendMessage } from "./send-message";

const idTaken = () =>
  ApiError.fromBody(409, {
    message: "That conversation id is taken.",
    code: "conversation_id_taken",
  });

const AT = "2026-11-12T10:00:00+00:00";
const NOW = new Date("2026-11-12T12:00:00Z");
const CONVERSATION = "conv-1";

const entry = (seq: number, logged: unknown) => ({
  kind: "entry",
  seq,
  at: AT,
  entry: logged,
});
const state = (
  head: number,
  display: string,
  work: { task_id: string; awaiting_approval: boolean }[] = [],
) => ({ kind: "state", head, display, work });
const replyText = (attemptId: string, index: number, text: string) => ({
  kind: "reply_delta",
  attempt_id: attemptId,
  reply_id: null,
  index,
  payload: { type: "response", response: text },
});
const workCard = (taskId: string, index: number, message: string) => ({
  kind: "work_delta",
  task_id: taskId,
  index,
  payload: {
    type: "tool_data",
    tool_data: {
      tool_name: "tool_calls_data",
      tool_category: "gmail",
      data: { tool_name: "send", tool_call_id: `${taskId}-${index}`, message },
      timestamp: AT,
    },
  },
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const lastStream = () => server.streams.at(-1) as OpenStream;
const live = () => liveConversation(CONVERSATION);
const rows = (conversationId = CONVERSATION) => {
  const { view, sends } = liveConversation(conversationId);
  return liveMessages(view, sends, NOW);
};
const loading = () => sendingLoadingRow(live().view, live().sends);

let release: (() => void) | null = null;

beforeEach(() => {
  server.streams = [];
  server.notFound.clear();
  sendResult.fail = null;
  sendResult.refusals = [];
  sendResult.calls = [];
  ids.next = 0;
  useLiveConversationStore.setState({ conversations: {} });
});

afterEach(() => {
  release?.();
  release = null;
  vi.useRealTimers();
});

describe("the mobile chat rendered from the conversation's events", () => {
  it("shows a streaming reply under the message it answers, then its saved text once settled", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    expect(lastStream().after).toBe(0);

    lastStream().push(entry(1, userMessage("m1", "hi")));
    lastStream().push(state(1, "thinking"));
    lastStream().push(replyText("a1", 0, "Hel"));
    lastStream().push(replyText("a1", 1, "lo"));

    expect(rows().map((row) => [row.isUser, row.text, row.inProgress])).toEqual(
      [
        [true, "hi", undefined],
        [false, "Hello", true],
      ],
    );
    expect(loading().visible).toBe(true);

    lastStream().push(entry(2, reply("r1", "a1", "Hello there")));
    lastStream().push(entry(3, replySettled("r1", ["m1"], 1)));
    lastStream().push(state(3, "idle"));

    expect(rows().map((row) => [row.text, row.inProgress])).toEqual([
      ["hi", undefined],
      ["Hello there", false],
    ]);
    expect(loading().visible).toBe(false);
  });

  it("shows a reaction-only answer as the reaction on the message, with no empty bubble", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1", "thanks!")));
    lastStream().push({
      kind: "entry_updated",
      seq: 1,
      entry: userMessage("m1", "thanks!", { emoji: "🙌", by: "chat_model" }, 1),
    });
    lastStream().push(entry(2, replySettled("r1", ["m1"], 1, null, "silent")));
    lastStream().push(state(2, "idle"));

    expect(rows()).toHaveLength(1);
    expect(rows()[0]?.reaction).toEqual({ emoji: "🙌", by: "chat_model" });
  });

  it("keeps a task's live cards after it finishes, until its reply settles", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const task = { task_id: "t1", awaiting_approval: false };
    lastStream().push(entry(1, userMessage("m1", "email bob")));
    lastStream().push(entry(2, workStarted("t1", 1)));
    lastStream().push(state(2, "working", [task]));
    lastStream().push(workCard("t1", 0, "Sending email"));

    const working = rows().at(-1);
    expect(working?.inProgress).toBe(true);
    expect(working?.toolData).toHaveLength(1);
    expect(loading().detail).toBe("Sending email");

    lastStream().push(entry(3, workFinished("t1", "done")));
    lastStream().push(state(3, "thinking"));
    expect(rows().at(-1)?.toolData).toHaveLength(1);

    lastStream().push(entry(4, reply("t1", "a2", "Sent.")));
    lastStream().push(entry(5, replySettled("t1", ["m1"], 1)));
    expect(rows().filter((row) => row.id.startsWith("work:"))).toHaveLength(0);
  });

  it("marks a stopped task's cards stopped instead of dropping them", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1")));
    lastStream().push(entry(2, workStarted("t1", 1)));
    lastStream().push(
      state(2, "working", [{ task_id: "t1", awaiting_approval: false }]),
    );
    lastStream().push(workCard("t1", 0, "Searching"));
    lastStream().push(entry(3, workFinished("t1", "cancelled")));
    lastStream().push(state(3, "idle"));

    const stopped = rows().at(-1);
    expect(stopped?.stopped).toBe(true);
    expect(stopped?.inProgress).toBe(false);
    expect(stopped?.toolData).toHaveLength(1);
  });

  it("words a failed reply that showed nothing by why it failed", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1")));
    lastStream().push(entry(2, reply("r1", "a1")));
    lastStream().push(
      entry(3, replySettled("r1", ["m1"], 1, null, "failed", "step_limit")),
    );

    expect(rows().at(-1)?.error).toBe(
      "GAIA took too many steps on this and stopped before answering.",
    );
  });
  it("shows a workflow run as the user's workflow card, then its reply", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, workflowFired("f1", "Morning brief")));
    lastStream().push(entry(2, reply("r1", "a1", "Three meetings today.")));
    lastStream().push(entry(3, replySettled("r1", ["f1"], 1)));

    expect(
      rows().map((row) => [row.isUser, row.text, row.firedWorkflow?.title]),
    ).toEqual([
      [true, "", "Morning brief"],
      [false, "Three meetings today.", undefined],
    ]);
  });

  it("shows a todo run as what woke it, then its write-up", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, todoWoke("w1")));
    lastStream().push(entry(2, workStarted("t1", 1)));
    lastStream().push(entry(3, workFinished("t1")));
    lastStream().push(entry(4, reply("t1", "a1", "The invoice was paid.")));
    lastStream().push(entry(5, replySettled("t1", ["w1"], 3)));

    expect(
      rows().map((row) => [row.isUser, row.text, row.todoRunWake?.kind]),
    ).toEqual([
      [true, "", "schedule"],
      [false, "The invoice was paid.", undefined],
    ]);
  });

  it("shows a notice as GAIA's message with the cards it was delivered with", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const card = toolCallCard("c1", "Checked the calendar");
    lastStream().push(entry(1, notice("n1", "Call the bank", [card])));

    expect(rows()).toMatchObject([
      { isUser: false, text: "Call the bank", toolData: [card] },
    ]);
  });
});

describe("following the events stream", () => {
  it("reconnects after a dropped socket from before what can still change", async () => {
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
    expect(lastStream().after).toBe(3);
  });

  it("reopens from the log when a delta skips an index", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const first = lastStream();
    first.push(entry(1, userMessage("m1")));
    first.push(replyText("a1", 0, "one "));
    first.push(replyText("a1", 2, "three"));
    await flush();

    expect(first.aborted()).toBe(true);
    expect(server.streams).toHaveLength(2);
    expect(lastStream().after).toBe(0);
  });

  it("stops following once released", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const stream = lastStream();
    release();
    release = null;
    expect(stream.aborted()).toBe(true);
  });
});

describe("sending", () => {
  it("shows the message before the server accepts it, and swaps it for the logged entry", async () => {
    server.notFound.add(CONVERSATION);
    release = openConversation(CONVERSATION);
    await flush();
    expect(server.streams).toHaveLength(0);

    server.notFound.delete(CONVERSATION);
    sendMessage(CONVERSATION, { text: "book it" });
    expect(rows()).toMatchObject([
      { id: "id-1", text: "book it", isUser: true, inProgress: true },
    ]);
    expect(loading()).toMatchObject({ visible: true, status: "thinking" });
    await flush();

    // The send woke the follower that was waiting on a 404.
    expect(server.streams).toHaveLength(1);
    expect(sendResult.calls[0]?.body.message_id).toBe("id-1");
    lastStream().push(entry(1, userMessage("id-1", "book it")));

    expect(rows()).toHaveLength(1);
    expect(rows()[0]?.id).toBe("id-1");
    expect(rows()[0]?.inProgress).toBeUndefined();
  });

  it("starts a new conversation under a minted id", () => {
    const conversationId = sendMessage(null, { text: "hi" });
    expect(conversationId).toBe("id-1");
    expect(sendResult.calls[0]?.conversationId).toBe("id-1");
  });

  it("starts the conversation over under a fresh id when its minted id is taken", async () => {
    sendResult.refusals = [idTaken()];
    const restarted = vi.fn();
    const first = sendMessage(null, { text: "hi" }, [], restarted);
    await flush();

    expect(sendResult.calls.map((call) => call.conversationId)).toEqual([
      first,
      "id-3",
    ]);
    expect(restarted).toHaveBeenCalledWith("id-3");
    expect(liveConversation(first).sends).toEqual({});
    expect(rows("id-3")[0]).toMatchObject({ text: "hi", sendFailed: false });
  });

  it("marks the send failed when the fresh id is taken too", async () => {
    sendResult.refusals = [idTaken(), idTaken()];
    const restarted = vi.fn();
    sendMessage(null, { text: "hi" }, [], restarted);
    await flush();

    expect(sendResult.calls).toHaveLength(2);
    expect(restarted).toHaveBeenCalledTimes(1);
    expect(rows("id-3")[0]).toMatchObject({ sendFailed: true });
  });

  it("marks a send that failed, and its retry resends the same message", async () => {
    sendResult.fail = new Error("offline");
    sendMessage(CONVERSATION, { text: "hello" });
    await flush();
    expect(rows()[0]).toMatchObject({ sendFailed: true, inProgress: false });
    expect(loading().visible).toBe(false);

    sendResult.fail = null;
    await retryMessage(CONVERSATION, "id-1");

    expect(sendResult.calls.map((call) => call.body.message_id)).toEqual([
      "id-1",
      "id-1",
    ]);
    expect(rows()[0]?.sendFailed).toBe(false);
  });

  it("puts up the paywall when the send is refused for a missing subscription", async () => {
    const offer = {
      code: "subscription_required",
      message: "GAIA is a paid product.",
      checkout_url: "https://checkout.dodo.test/abc",
      discount_code: null,
    };
    sendResult.fail = ApiError.fromBody(402, offer);
    sendMessage(CONVERSATION, { text: "hello" });
    await flush();

    expect(usePaywallStore.getState().offer).toEqual(offer);
    expect(rows()[0]?.sendFailed).toBe(true);
  });

  it("retries a failed reply by asking the server to answer its message again", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    lastStream().push(entry(1, userMessage("m1", "plan my day")));
    lastStream().push(entry(2, reply("r1", "a1")));
    lastStream().push(entry(3, replySettled("r1", ["m1"], 1, null, "failed")));

    await retryMessage(CONVERSATION, "r1");

    expect(sendResult.calls[0]?.body).toMatchObject({ target: "m1" });
  });
});
