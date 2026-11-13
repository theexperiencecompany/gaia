// @vitest-environment jsdom
import {
  type ConversationFrame,
  type ConversationPage,
  type Entry,
  REPLY_FAILURE_MESSAGE,
} from "@shared/conversation";
import {
  approvalDecided,
  approvalRequested,
  entryFrame,
  entryUpdatedFrame,
  notice,
  reply,
  replyDelta,
  replySettled,
  stateFrame,
  todoWoke,
  toolCallCard,
  userMessage,
  workFinished,
  workflowFired,
  workStarted,
} from "@shared/conversation/testing";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";
import { useChatStore } from "@/stores/chatStore";
import { useConversation } from "./useConversation";

const CONVERSATION = "conv-1";
const ALL_LIVE = "conv-all-live";
const AT = "2026-11-13T09:00:00+00:00";
const IMAGE = { url: "https://img.test/cat.png", prompt: "a cat" };
const APPROVAL_CARD = {
  tool_name: "approval_request",
  tool_category: "gmail",
  data: { approval_id: "ap1", outcome: null, summary: "Send the email" },
  timestamp: AT,
};
const WORK_CARD = toolCallCard("c2", "Checked the invoice");

const imageReply = {
  ...reply("r2", "a2", "Here is the picture."),
  image: IMAGE,
  pinned: true,
} as Entry;
const narration = {
  ...reply("t1", "a1", "Sent the email to your landlord."),
  tool_data: [APPROVAL_CARD],
} as Entry;

// The log as the server held it while r3 was still streaming.
const LOG: Entry[] = [
  userMessage("m1", "email the landlord"),
  workStarted("t1", 1),
  approvalRequested("t1", "ap1"),
  approvalDecided("ap1"),
  workFinished("t1", "done", [APPROVAL_CARD]),
  narration,
  replySettled("t1", ["m1"], 1),
  notice("n1", "Reminder: pay rent"),
  workflowFired("f1", "Morning brief"),
  imageReply,
  replySettled("r2", ["f1"], 9),
  todoWoke("w1"),
  workStarted("t2", 12),
  workFinished("t2", "done", [WORK_CARD]),
  userMessage("m3", "and tomorrow?"),
  reply("r3", "a3", "Tomorrow you"),
];
const LOGGED = LOG.map((entry, at) => entryFrame(at + 1, entry));
const HEAD = LOG.length;
const LOADED_STATE = stateFrame(HEAD, "thinking");

const page = (frames: ConversationFrame[]): ConversationPage => ({
  entries: frames.flatMap((frame) => (frame.kind === "entry" ? [frame] : [])),
  state: { kind: "state", head: HEAD, display: "thinking", work: [] },
  has_older: false,
  cursor: null,
});

// What arrives after the load: r3 fills in and settles.
const AFTER: ConversationFrame[] = [
  entryUpdatedFrame(HEAD, reply("r3", "a3", "Tomorrow you have one call.", 1)),
  entryFrame(HEAD + 1, replySettled("r3", ["m3"], HEAD - 1)),
  stateFrame(HEAD + 1, "idle"),
];

const show = (conversationId: string) =>
  useChatStore.setState({
    activeConversationId: conversationId,
    optimisticMessage: null,
  });

const load = (conversationId: string, loaded: ConversationPage) =>
  act(() => {
    useLiveConversationStore.getState().applyPage(conversationId, loaded);
  });

const feed = (conversationId: string, ...frames: ConversationFrame[]) =>
  act(() => {
    useLiveConversationStore.getState().applyFrames(conversationId, frames);
  });

const rowsOf = (conversationId: string) => {
  show(conversationId);
  return renderHook(() => useConversation()).result.current.convoMessages;
};

beforeEach(() => {
  useLiveConversationStore.setState({ conversations: {} });
});

describe("a conversation loaded from history, then continued live", () => {
  it("renders the same rows, in the same order, as an all-live session of the log", async () => {
    await load(CONVERSATION, page(LOGGED));
    await feed(CONVERSATION, ...AFTER);
    await feed(ALL_LIVE, ...LOGGED, LOADED_STATE, ...AFTER);

    const shown = rowsOf(CONVERSATION);
    expect(shown).toEqual(rowsOf(ALL_LIVE));
    expect(shown.map((row) => row.message_id)).toEqual([
      "m1",
      "t1",
      "n1",
      "f1",
      "r2",
      "w1",
      "work:t2",
      "m3",
      "r3",
    ]);
    const byId = new Map(shown.map((row) => [row.message_id, row]));
    expect(byId.get("t1")?.tool_data?.[0]?.data).toMatchObject({
      approval_id: "ap1",
      outcome: "approved",
    });
    expect(byId.get("r2")?.image_data).toEqual(IMAGE);
    expect(byId.get("r2")?.pinned).toBe(true);
    expect(byId.get("f1")?.selectedWorkflow?.title).toBe("Morning brief");
    expect(byId.get("w1")?.todo_run_wake?.kind).toBe("schedule");
    expect(byId.get("work:t2")?.tool_data).toEqual([WORK_CARD]);
    expect(byId.get("r3")?.response).toBe("Tomorrow you have one call.");
  });

  it("finishes a reply that was mid-stream when the page reloaded, in its own row", async () => {
    await load(CONVERSATION, page(LOGGED));
    const open = rowsOf(CONVERSATION).filter((row) => row.message_id === "r3");
    expect(open).toHaveLength(1);
    expect(open[0]?.in_progress).toBe(false);

    await feed(
      CONVERSATION,
      replyDelta("a3", "r3", 0, "Tomorrow you have one call."),
      ...AFTER,
    );
    const finished = rowsOf(CONVERSATION).filter(
      (row) => row.message_id === "r3",
    );
    expect(finished).toHaveLength(1);
    expect(finished[0]?.response).toBe("Tomorrow you have one call.");
    expect(finished[0]?.in_progress).toBe(false);
    expect(rowsOf(CONVERSATION).at(-1)?.message_id).toBe("r3");
  });

  it("words a failed reply loaded from history by its reason code", async () => {
    await load(
      CONVERSATION,
      page([
        entryFrame(1, userMessage("m1", "summarise my inbox")),
        entryFrame(2, reply("r1", "a1")),
        entryFrame(
          3,
          replySettled("r1", ["m1"], 1, null, "failed", "step_limit"),
        ),
      ]),
    );
    expect(rowsOf(CONVERSATION).at(-1)?.error).toBe(
      REPLY_FAILURE_MESSAGE.step_limit,
    );
  });
});
