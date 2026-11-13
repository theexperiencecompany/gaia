// @vitest-environment jsdom
import type { ConversationEntry } from "@shared/api/generated";
import {
  type ConversationFrame,
  type Entry,
  REPLY_FAILURE_MESSAGE,
} from "@shared/conversation";
import {
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
import { storedMessagesFromHistory } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";
import { useConversation } from "./useConversation";

const CONVERSATION = "conv-1";
const AT = "2026-11-13T09:00:00+00:00";
const IMAGE = { url: "https://img.test/cat.png", prompt: "a cat" };
const APPROVAL_CARD = {
  tool_name: "approval_request",
  tool_category: "gmail",
  data: { approval_id: "ap1", status: "approved", summary: "Send the email" },
  timestamp: AT,
};
const WORK_CARD = toolCallCard("c2", "Checked the invoice");

const bot = (
  seq: number,
  messageId: string,
  fields: Partial<ConversationEntry> = {},
): ConversationEntry => ({
  seq,
  date: AT,
  type: "bot",
  response: "",
  message_id: messageId,
  ...fields,
});

const user = (
  seq: number,
  messageId: string,
  fields: Partial<ConversationEntry> = {},
): ConversationEntry => ({
  seq,
  date: AT,
  type: "user",
  response: "",
  message_id: messageId,
  ...fields,
});

// The server's history of the log below, read while r3 was still streaming.
const HISTORY: ConversationEntry[] = [
  user(1, "m1", { response: "email the landlord" }),
  bot(5, "t1", {
    response: "Sent the email to your landlord.",
    tool_data: [APPROVAL_CARD],
  }),
  bot(7, "n1", { response: "Reminder: pay rent" }),
  user(8, "f1", {
    selectedWorkflow: {
      id: "wf-f1",
      title: "Morning brief",
      description: "",
      steps: [],
    },
  }),
  bot(9, "r2", {
    response: "Here is the picture.",
    image_data: IMAGE,
    pinned: true,
  }),
  user(11, "w1", {
    todo_run_wake: {
      kind: "schedule",
      trigger_names: [],
      approval_summary: null,
    },
  }),
  bot(12, "work:t2", { tool_data: [WORK_CARD] }),
  user(14, "m3", { response: "and tomorrow?" }),
  bot(15, "r3", { response: "Tomorrow you", in_progress: true }),
];

const imageReply = {
  ...reply("r2", "a2", "Here is the picture."),
  image: IMAGE,
  pinned: true,
} as Entry;

// The events stream replays from the notice on: every entry the history also shows.
const REPLAY: ConversationFrame[] = [
  entryFrame(7, notice("n1", "Reminder: pay rent")),
  entryFrame(8, workflowFired("f1", "Morning brief")),
  entryFrame(9, imageReply),
  entryFrame(10, replySettled("r2", ["f1"], 8)),
  entryFrame(11, todoWoke("w1")),
  entryFrame(12, workStarted("t2", 11)),
  entryFrame(13, workFinished("t2", "done", [WORK_CARD])),
  entryFrame(14, userMessage("m3", "and tomorrow?")),
  entryFrame(15, reply("r3", "a3", "Tomorrow you")),
  stateFrame(15, "thinking"),
];

const seedHistory = (history: ConversationEntry[]) =>
  useChatStore.setState({
    activeConversationId: CONVERSATION,
    messagesByConversation: {
      [CONVERSATION]: storedMessagesFromHistory(history, CONVERSATION),
    },
    optimisticMessage: null,
  });

const feed = (...frames: ConversationFrame[]) =>
  act(() => {
    useLiveConversationStore.getState().applyFrames(CONVERSATION, frames);
  });

const rows = () => renderHook(() => useConversation()).result;

beforeEach(() => {
  useLiveConversationStore.setState({ conversations: {} });
});

describe("a conversation loaded from history, then continued live", () => {
  it("shows every row once, in the log's order", async () => {
    seedHistory(HISTORY);
    const result = rows();
    await feed(...REPLAY);
    await feed(
      entryUpdatedFrame(
        15,
        reply("r3", "a3", "Tomorrow you have one call.", 1),
      ),
      entryFrame(16, replySettled("r3", ["m3"], 14)),
      stateFrame(16, "idle"),
    );

    const shown = result.current.convoMessages;
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
    expect(byId.get("t1")?.tool_data).toEqual([APPROVAL_CARD]);
    expect(byId.get("r2")?.image_data).toEqual(IMAGE);
    expect(byId.get("r2")?.pinned).toBe(true);
    expect(byId.get("f1")?.selectedWorkflow?.title).toBe("Morning brief");
    expect(byId.get("w1")?.todo_run_wake?.kind).toBe("schedule");
    expect(byId.get("work:t2")?.tool_data).toEqual([WORK_CARD]);
  });

  it("finishes a reply that was mid-stream when the page reloaded, in its own row", async () => {
    seedHistory(HISTORY);
    const result = rows();
    await feed(entryFrame(15, reply("r3", "a3", "Tomorrow you")));
    expect(
      result.current.convoMessages.filter((row) => row.message_id === "r3"),
    ).toHaveLength(1);

    await feed(
      replyDelta("a3", "r3", 0, "Tomorrow you have one call."),
      entryUpdatedFrame(
        15,
        reply("r3", "a3", "Tomorrow you have one call.", 1),
      ),
      entryFrame(16, replySettled("r3", ["m3"], 14)),
    );
    const finished = result.current.convoMessages.filter(
      (row) => row.message_id === "r3",
    );
    expect(finished).toHaveLength(1);
    expect(finished[0]?.in_progress).toBe(false);
    expect(result.current.convoMessages.at(-1)?.message_id).toBe("r3");
  });

  it("words a failed reply in history by its reason code", () => {
    seedHistory([
      user(1, "m1", { response: "summarise my inbox" }),
      bot(2, "r1", { error: "step_limit" }),
    ]);
    const failed = rows().current.convoMessages.at(-1);
    expect(failed?.error).toBe(REPLY_FAILURE_MESSAGE.step_limit);
  });

  it("words an unknown failure code as a model error, never as the raw code", () => {
    seedHistory([bot(1, "r1", { error: "something_new" })]);
    expect(rows().current.convoMessages[0]?.error).toBe(
      REPLY_FAILURE_MESSAGE.model_error,
    );
  });
});
