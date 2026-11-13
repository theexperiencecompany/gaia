import type { ConversationFrame, Entry } from "@gaia/shared/conversation";
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
} from "@gaia/shared/conversation/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { applyConversationPage } from "./connection";
import {
  liveConversation,
  useLiveConversationStore,
} from "./live-conversation-store";
import { liveMessages } from "./live-messages";

const { getMock, saved } = vi.hoisted(() => ({
  getMock: vi.fn(),
  saved: new Map<string, unknown>(),
}));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@gaia/shared")>("@gaia/shared");
  return {
    ApiError: actual.ApiError,
    apiService: { get: getMock, post: vi.fn(), put: vi.fn() },
  };
});

vi.mock("@/lib/db/chatDb", () => ({
  chatDb: {
    getLog: async (id: string) => saved.get(id) ?? null,
    saveLog: async (id: string, log: unknown) => {
      saved.set(id, log);
    },
  },
}));

vi.mock("@/lib/query-provider", () => ({ queryClient: {} }));

const NOW = new Date("2026-11-13T09:00:00Z");
const AT = "2026-11-13T09:00:00+00:00";
const IMAGE = { url: "https://img.test/cat.png", prompt: "a cat" };
const APPROVAL_CARD = {
  tool_name: "approval_request",
  tool_category: "gmail",
  data: { approval_id: "ap1", status: "pending", summary: "Send the email" },
  timestamp: AT,
};
const WORK_CARD = toolCallCard("c2", "Checked the invoice");

const LOG: Entry[] = [
  userMessage("m1", "email the landlord"),
  workStarted("t1", 1),
  approvalRequested("t1", "ap1"),
  approvalDecided("ap1"),
  workFinished("t1", "done", [APPROVAL_CARD]),
  {
    ...reply("t1", "a1", "Sent the email to your landlord."),
    tool_data: [APPROVAL_CARD],
  } as Entry,
  replySettled("t1", ["m1"], 1),
  notice("n1", "Reminder: pay rent"),
  workflowFired("f1", "Morning brief"),
  {
    ...reply("r2", "a2", "Here is the picture."),
    image: IMAGE,
    pinned: true,
  } as Entry,
  replySettled("r2", ["f1"], 9),
  todoWoke("w1"),
  workStarted("t2", 12),
  workFinished("t2", "done", [WORK_CARD]),
  userMessage("m3", "and tomorrow?"),
  reply("r3", "a3", "Tomorrow you"),
];
const HEAD = LOG.length;
const LOGGED = LOG.map((entry, at) => entryFrame(at + 1, entry));
const AFTER: ConversationFrame[] = [
  entryUpdatedFrame(HEAD, reply("r3", "a3", "Tomorrow you have one call.", 1)),
  entryFrame(HEAD + 1, replySettled("r3", ["m3"], HEAD - 1)),
  stateFrame(HEAD + 1, "idle"),
];

const rows = (conversationId: string) =>
  liveMessages(liveConversation(conversationId).view, {}, NOW);

/** The server's GET /conversations/{id}: the log's entries and the head's state. */
const serveLoad = () =>
  getMock.mockResolvedValue({
    conversation_id: "conv-1",
    entries: LOGGED,
    state: { kind: "state", head: HEAD, display: "thinking", work: [] },
    has_older: false,
    cursor: null,
  });

const load = async () => {
  serveLoad();
  const { fetchConversationPage } = await import("../api/chat-api");
  await applyConversationPage("conv-1", await fetchConversationPage("conv-1"));
};

beforeEach(() => {
  getMock.mockReset();
  saved.clear();
  useLiveConversationStore.setState({ conversations: {} });
});

describe("a mobile conversation loaded from history, then continued live", () => {
  it("renders the same rows, in the same order, as an all-live session of the log", async () => {
    await load();
    useLiveConversationStore.getState().applyFrames("conv-1", AFTER);
    useLiveConversationStore
      .getState()
      .applyFrames("all-live", [
        ...LOGGED,
        stateFrame(HEAD, "thinking"),
        ...AFTER,
      ]);

    const shown = rows("conv-1");
    expect(shown).toEqual(rows("all-live"));
    expect(shown.map((message) => message.id)).toEqual([
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
    const byId = new Map(shown.map((message) => [message.id, message]));
    expect(byId.get("t1")?.toolData?.[0]?.data).toMatchObject({
      status: "approved",
    });
    expect(byId.get("r2")?.imageData).toEqual(IMAGE);
    expect(byId.get("f1")?.firedWorkflow?.title).toBe("Morning brief");
    expect(byId.get("work:t2")?.toolData).toEqual([WORK_CARD]);
    expect(byId.get("r3")?.text).toBe("Tomorrow you have one call.");
  });

  it("saves the folded log and its cursor, so a reload restores it before the stream resumes", async () => {
    await load();

    expect(saved.get("conv-1")).toEqual({
      entries: liveConversation("conv-1").view.entries,
      olderBefore: null,
    });
  });

  it("finishes a reply that was mid-stream when the app reloaded, in its own row", async () => {
    await load();
    useLiveConversationStore
      .getState()
      .applyFrames("conv-1", [
        replyDelta("a3", "r3", 0, "Tomorrow you have one call."),
        ...AFTER,
      ]);

    const r3 = rows("conv-1").filter((message) => message.id === "r3");
    expect(r3).toHaveLength(1);
    expect(r3[0]?.inProgress).toBe(false);
  });
});
