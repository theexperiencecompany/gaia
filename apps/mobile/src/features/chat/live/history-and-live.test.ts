import type { ConversationEntry } from "@gaia/shared/api/generated";
import {
  applyFrame,
  type ConversationFrame,
  type ConversationView,
  EMPTY_CONVERSATION_VIEW,
  type Entry,
  REPLY_FAILURE_MESSAGE,
  withLiveRows,
} from "@gaia/shared/conversation";
import {
  entryFrame,
  entryUpdatedFrame,
  notice,
  reply,
  replyDelta,
  replySettled,
  todoWoke,
  toolCallCard,
  userMessage,
  workFinished,
  workflowFired,
  workStarted,
} from "@gaia/shared/conversation/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchConversation, type Message } from "../api/chat-api";
import { liveMessages } from "./live-messages";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@gaia/shared")>("@gaia/shared");
  return {
    ApiError: actual.ApiError,
    apiService: { get: getMock, post: vi.fn(), put: vi.fn() },
    API_BASE_URL: "http://test.local/api/v1",
  };
});

const AT = "2026-11-13T09:00:00+00:00";
const NOW = new Date(AT);
const IMAGE = { url: "https://img.test/cat.png", prompt: "a cat" };
const APPROVAL_CARD = {
  tool_name: "approval_request",
  tool_category: "gmail",
  data: { approval_id: "ap1", status: "approved", summary: "Send the email" },
  timestamp: AT,
};
const WORK_CARD = toolCallCard("c2", "Checked the invoice");
const WORKFLOW = {
  id: "wf-f1",
  title: "Morning brief",
  description: "",
  steps: [],
};

const row = (
  seq: number,
  type: "user" | "bot",
  messageId: string,
  fields: Partial<ConversationEntry> = {},
): ConversationEntry => ({
  seq,
  date: AT,
  type,
  response: "",
  message_id: messageId,
  ...fields,
});

// The server's history of the log below, read while r3 was still streaming.
const HISTORY: ConversationEntry[] = [
  row(1, "user", "m1", { response: "email the landlord" }),
  row(5, "bot", "t1", {
    response: "Sent the email to your landlord.",
    tool_data: [APPROVAL_CARD],
  }),
  row(7, "bot", "n1", { response: "Reminder: pay rent" }),
  row(8, "user", "f1", { selectedWorkflow: WORKFLOW }),
  row(9, "bot", "r2", {
    response: "Here is the picture.",
    image_data: IMAGE,
    pinned: true,
  }),
  row(11, "user", "w1", {
    todo_run_wake: {
      kind: "schedule",
      trigger_names: [],
      approval_summary: null,
    },
  }),
  row(12, "bot", "work:t2", { tool_data: [WORK_CARD] }),
  row(14, "user", "m3", { response: "and tomorrow?" }),
  row(15, "bot", "r3", { response: "Tomorrow you", in_progress: true }),
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
];

const fold = (frames: ConversationFrame[]): ConversationView =>
  frames.reduce((view, frame) => {
    const outcome = applyFrame(view, frame);
    if (outcome.status !== "applied")
      throw new Error(`frame not applied: ${outcome.status}`);
    return outcome.view;
  }, EMPTY_CONVERSATION_VIEW);

const loadHistory = async (history: ConversationEntry[]) => {
  getMock.mockResolvedValue({
    _id: "head-1",
    user_id: "u1",
    conversation_id: "conv-1",
    description: "Landlord",
    is_unread: false,
    has_older: false,
    messages: history,
    createdAt: AT,
    updatedAt: AT,
  });
  const detail = await fetchConversation("conv-1");
  if (!detail) throw new Error("history did not load");
  return detail.messages;
};

const shown = (saved: Message[], frames: ConversationFrame[]) =>
  withLiveRows(saved, liveMessages(fold(frames), {}, NOW), (row) => row.id);

beforeEach(() => {
  getMock.mockReset();
});

describe("a mobile conversation loaded from history, then continued live", () => {
  it("shows every row once, in the log's order", async () => {
    const rows = shown(await loadHistory(HISTORY), [
      ...REPLAY,
      entryUpdatedFrame(
        15,
        reply("r3", "a3", "Tomorrow you have one call.", 1),
      ),
      entryFrame(16, replySettled("r3", ["m3"], 14)),
    ]);

    expect(rows.map((message) => message.id)).toEqual([
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
    const byId = new Map(rows.map((message) => [message.id, message]));
    expect(byId.get("t1")?.toolData).toEqual([APPROVAL_CARD]);
    expect(byId.get("r2")?.imageData).toEqual(IMAGE);
    expect(byId.get("r2")?.pinned).toBe(true);
    expect(byId.get("f1")?.firedWorkflow?.title).toBe("Morning brief");
    expect(byId.get("w1")?.todoRunWake?.kind).toBe("schedule");
    expect(byId.get("work:t2")?.toolData).toEqual([WORK_CARD]);
    expect(byId.get("r3")?.text).toBe("Tomorrow you have one call.");
    expect(byId.get("r3")?.inProgress).toBe(false);
  });

  it("keeps the history's fields on a row the live view has not reached", async () => {
    const saved = await loadHistory([
      row(9, "bot", "r2", {
        response: "Here is the picture.",
        image_data: IMAGE,
        pinned: true,
      }),
      row(10, "bot", "r4", { response: "Still going", in_progress: true }),
      row(11, "bot", "r5", { stopped: true }),
    ]);

    expect(saved[0]).toMatchObject({ imageData: IMAGE, pinned: true });
    expect(saved[1]?.inProgress).toBe(true);
    expect(saved[2]?.stopped).toBe(true);
  });

  it("shows a reply that was mid-stream at reload once, finishing in place", async () => {
    const saved = await loadHistory(HISTORY);
    const streaming = shown(saved, [
      entryFrame(15, reply("r3", "a3", "Tomorrow you")),
      replyDelta("a3", "r3", 0, "Tomorrow you have"),
    ]);
    expect(streaming.filter((message) => message.id === "r3")).toHaveLength(1);
    expect(streaming.at(-1)?.inProgress).toBe(true);
  });

  it("words a failed reply in history by its reason code", async () => {
    const [failed] = await loadHistory([
      row(2, "bot", "r1", { error: "server_restart" }),
    ]);
    expect(failed?.error).toBe(REPLY_FAILURE_MESSAGE.server_restart);
  });
});
