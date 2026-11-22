import type { ScreenItem } from "@gaia/shared/conversation";
import {
  insertFrame,
  noticeItem,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  toolCallCard,
  updateFrame,
  userItem,
  workItem,
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

vi.mock("expo-crypto", () => ({ randomUUID: () => "id-1" }));

const NOW = new Date("2026-11-13T09:00:00Z");
const WORK_CARD = toolCallCard("c2", "Checked the invoice");

const SCREEN: ScreenItem[] = [
  userItem("m1", 1, "email the landlord"),
  { ...workItem("t1", 2, "done"), tool_data: [WORK_CARD] },
  replyItem("r1", 3, "Sent the email to your landlord.", "answered"),
  noticeItem("n1", 4, "Reminder: pay rent"),
  userItem("m3", 5, "and tomorrow?"),
  replyItem("r3", 6, "Tomorrow you"),
];
const HEAD = 6;
const FINISHED = replyItem("r3", 6, "Tomorrow you have one call.", "answered");
const AFTER = [updateFrame(FINISHED, HEAD + 1), stateFrame(HEAD + 1, "idle")];

const rows = (conversationId: string) =>
  liveMessages(liveConversation(conversationId).view, {}, NOW);

/** The server's GET /conversations/{id}: the screen's newest page and the head's state. */
const load = async () => {
  getMock.mockResolvedValue({
    conversation_id: "conv-1",
    items: SCREEN,
    state: { kind: "state", head: HEAD, display: "thinking", work: [] },
    has_older: false,
    cursor: null,
  });
  const { fetchConversationPage } = await import("../api/chat-api");
  await applyConversationPage("conv-1", await fetchConversationPage("conv-1"));
};

beforeEach(() => {
  getMock.mockReset();
  saved.clear();
  useLiveConversationStore.setState({ conversations: {} });
});

describe("a mobile conversation loaded from history, then continued live", () => {
  it("renders the same rows, in the same order, as a session that followed the screen live", async () => {
    await load();
    useLiveConversationStore.getState().applyFrames("conv-1", AFTER);
    useLiveConversationStore
      .getState()
      .applyFrames("all-live", [
        screenFrame(SCREEN, HEAD),
        stateFrame(HEAD, "thinking"),
        ...AFTER,
      ]);

    const shown = rows("conv-1");
    expect(shown).toEqual(rows("all-live"));
    expect(shown.map((message) => message.id)).toEqual([
      "m1",
      "work:t1",
      "r1",
      "n1",
      "m3",
      "r3",
    ]);
    const byId = new Map(shown.map((message) => [message.id, message]));
    expect(byId.get("work:t1")?.toolData).toEqual([WORK_CARD]);
    expect(byId.get("r3")?.text).toBe("Tomorrow you have one call.");
  });

  it("saves the screen, its head and its cursor, so a reload restores it before the stream resumes", async () => {
    await load();

    expect(saved.get("conv-1")).toEqual({
      items: liveConversation("conv-1").view.items,
      head: HEAD,
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
    expect(r3[0]?.text).toBe("Tomorrow you have one call.");
  });

  it("adds an item the stream inserts after the loaded page below it", async () => {
    await load();
    useLiveConversationStore
      .getState()
      .applyFrames("conv-1", [
        insertFrame(noticeItem("n2", HEAD + 1, "Your call is at 3pm")),
      ]);

    expect(rows("conv-1").at(-1)?.id).toBe("n2");
  });
});
