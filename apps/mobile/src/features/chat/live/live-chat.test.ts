import { ApiError } from "@gaia/shared";
import type { ScreenItem } from "@gaia/shared/conversation";
import { sendingLoadingRow } from "@gaia/shared/conversation";
import {
  insertFrame,
  liveTask,
  noticeItem,
  replyDelta,
  replyItem,
  stateFrame,
  toolCallCard,
  updateFrame,
  userItem,
  userItemWith,
  workItem,
} from "@gaia/shared/conversation/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A fake events endpoint: each subscription is a stream the test feeds frames to
 * and then ends, drops, or refuses with 404.
 */
interface OpenStream {
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

vi.mock("@/lib/db/chatDb", () => ({
  chatDb: { getLog: async () => null, saveLog: async () => undefined },
}));

vi.mock("../api/queries", () => ({
  chatKeys: { conversations: () => ["chat", "conversations"] },
}));

vi.mock("../api/chat-api", async () => {
  const { EventStreamHttpError } = await import("@/lib/sse-client");
  return {
    chatApi: {
      subscribeToConversationEvents: (
        conversationId: string,
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

const progress = (message: string) => ({
  message,
  tool_name: "send",
  tool_category: "gmail",
  integration_name: null,
  icon_url: null,
  show_category: true,
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const lastStream = () => server.streams.at(-1) as OpenStream;
const live = () => liveConversation(CONVERSATION);
const rows = (conversationId = CONVERSATION) => {
  const { view, sends } = liveConversation(conversationId);
  return liveMessages(view, sends, NOW);
};
const loading = () => sendingLoadingRow(live().view, live().sends);
const show = (...items: ScreenItem[]) => {
  for (const item of items) lastStream().push(insertFrame(item));
};

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

describe("the mobile chat rendered from the conversation's screen", () => {
  it("shows a streaming reply under the message it answers, then its saved text once settled", async () => {
    release = openConversation(CONVERSATION);
    await flush();

    show(userItem("m1", 1, "hi"));
    lastStream().push(stateFrame(1, "thinking"));
    lastStream().push(replyDelta("a1", "r1", 0, "Hel"));
    lastStream().push(replyDelta("a1", "r1", 1, "lo"));

    expect(rows().map((row) => [row.isUser, row.text, row.inProgress])).toEqual(
      [
        [true, "hi", undefined],
        [false, "Hello", true],
      ],
    );
    expect(loading().visible).toBe(true);

    show(replyItem("r1", 2, "Hello there", "answered"));
    lastStream().push(stateFrame(2, "idle"));

    expect(rows().map((row) => [row.text, row.inProgress])).toEqual([
      ["hi", undefined],
      ["Hello there", false],
    ]);
    expect(loading().visible).toBe(false);
  });

  it("shows a reaction on the message it was given to", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    show(userItem("m1", 1, "thanks!"));
    lastStream().push(
      updateFrame(
        userItemWith("m1", 1, {
          text: "thanks!",
          reaction: { emoji: "🙌", by: "chat_model" },
        }),
        2,
      ),
    );
    lastStream().push(stateFrame(2, "idle"));

    expect(rows()).toHaveLength(1);
    expect(rows()[0]?.reaction).toEqual({ emoji: "🙌", by: "chat_model" });
  });

  it("shows a task's cards while it runs, with the server's progress line, and keeps them once it finishes", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const card = toolCallCard("t1-0", "Sending email");
    const running = {
      ...workItem("t1", 2, "running"),
      tool_data: [card],
      timeline: { steps: [], cards: [], progress: progress("Sending email") },
    };
    show(userItem("m1", 1, "email bob"), running);
    lastStream().push(stateFrame(2, "working", [liveTask("t1")]));

    const working = rows().at(-1);
    expect(working?.inProgress).toBe(true);
    expect(working?.toolData).toEqual([card]);
    expect(loading().progress?.message).toBe("Sending email");

    lastStream().push(
      updateFrame({ ...workItem("t1", 2, "done"), tool_data: [card] }, 3),
    );
    lastStream().push(stateFrame(3, "thinking"));
    expect(rows().at(-1)?.toolData).toEqual([card]);
  });

  it("marks a stopped task's cards stopped instead of dropping them", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const card = toolCallCard("t1-0", "Searching");
    show(userItem("m1", 1), {
      ...workItem("t1", 2, "cancelled"),
      tool_data: [card],
    });
    lastStream().push(stateFrame(3, "idle"));

    const stopped = rows().at(-1);
    expect(stopped?.stopped).toBe(true);
    expect(stopped?.inProgress).toBe(false);
    expect(stopped?.toolData).toEqual([card]);
  });

  it("words a failed reply that showed nothing by why it failed", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    show(userItem("m1", 1), {
      ...replyItem("r1", 2, "", "failed"),
      failure: "step_limit",
    });

    expect(rows().at(-1)?.error).toBe(
      "GAIA took too many steps on this and stopped before answering.",
    );
  });

  it("shows a workflow run as the user's workflow card, then its reply", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    show(
      {
        kind: "workflow_fired",
        id: "f1",
        seq: 1,
        at: AT,
        workflow: {
          id: "wf-f1",
          title: "Morning brief",
          description: "",
          steps: [],
        },
      } as ScreenItem,
      replyItem("r1", 2, "Three meetings today.", "answered"),
    );

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
    show(
      {
        kind: "todo_woke",
        id: "w1",
        seq: 1,
        at: AT,
        wake: { kind: "schedule", trigger_names: [], approval_summary: null },
      } as ScreenItem,
      replyItem("t1", 2, "The invoice was paid.", "answered"),
    );

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
    show({ ...noticeItem("n1", 1, "Call the bank"), tool_data: [card] });

    expect(rows()).toMatchObject([
      { isUser: false, text: "Call the bank", toolData: [card] },
    ]);
  });
});

describe("following the events stream", () => {
  it("reconnects after a dropped socket", async () => {
    vi.useFakeTimers();
    release = openConversation(CONVERSATION);
    await vi.advanceTimersByTimeAsync(0);
    const first = lastStream();
    first.push(insertFrame(userItem("m1", 1)));
    first.drop(new Error("socket lost"));

    await vi.advanceTimersByTimeAsync(1_000);

    expect(server.streams).toHaveLength(2);
    expect(rows().map((row) => row.id)).toEqual(["m1"]);
  });

  it("reopens from the log when a delta skips an index", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    const first = lastStream();
    first.push(insertFrame(userItem("m1", 1)));
    first.push(replyDelta("a1", null, 0, "one "));
    first.push(replyDelta("a1", null, 2, "three"));
    await flush();

    expect(first.aborted()).toBe(true);
    expect(server.streams).toHaveLength(2);
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
  it("shows the message before the server accepts it, and swaps it for the logged item", async () => {
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
    lastStream().push(insertFrame(userItem("id-1", 1, "book it")));

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

  it("retries a failed reply by asking the server to answer the message it names", async () => {
    release = openConversation(CONVERSATION);
    await flush();
    show(userItem("m1", 1, "plan my day"), {
      ...replyItem("r1", 2, "", "failed"),
      retry_target: "m1",
    });

    await retryMessage(CONVERSATION, "r1");

    expect(sendResult.calls[0]?.body).toMatchObject({ target: "m1" });
  });
});
