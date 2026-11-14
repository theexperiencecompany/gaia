import { ApiError } from "@gaia/shared";
import { userItem } from "@gaia/shared/conversation/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchConversationPage,
  fetchEntriesBefore,
  postApprovalDecision,
  sendConversationMessage,
  stopConversation,
} from "./chat-api";

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@gaia/shared")>("@gaia/shared");
  return {
    ApiError: actual.ApiError,
    apiService: { get: getMock, post: postMock },
    API_BASE_URL: "http://test.local/api/v1",
  };
});

describe("postApprovalDecision", () => {
  beforeEach(() => {
    postMock.mockReset();
  });

  it("returns the server's verdict when a stale tap is rejected (200, success:false)", async () => {
    // Regression: the client used to return `true` on any 2xx, so an
    // already-resolved tap read as a fresh approval and the card stuck disabled.
    postMock.mockResolvedValue({ success: false, status: "approved" });

    const outcome = await postApprovalDecision("appr-1", {
      decision: "approve",
    });

    expect(outcome).toEqual({ success: false, status: "approved" });
  });

  it("passes a committed decision through unchanged", async () => {
    postMock.mockResolvedValue({ success: true });

    const outcome = await postApprovalDecision("appr-1", { decision: "deny" });

    expect(outcome.success).toBe(true);
  });

  it("maps a 410 to not_found so the card refreshes instead of settling", async () => {
    postMock.mockRejectedValue(new ApiError("Gone", 410));

    const outcome = await postApprovalDecision("appr-1", {
      decision: "approve",
    });

    expect(outcome).toEqual({ success: false, reason: "not_found" });
  });

  it("re-throws a genuine failure instead of swallowing it as success", async () => {
    postMock.mockRejectedValue(new ApiError("Server error", 500));

    await expect(
      postApprovalDecision("appr-1", { decision: "approve" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

const PAGE = {
  items: [userItem("m-3", 3, "thanks")],
  state: { kind: "state", head: 3, display: "idle", work: [] },
  has_older: true,
  cursor: 3,
};

describe("loading the log", () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it("reads a conversation as its newest page of screen items, with the head's state", async () => {
    getMock.mockResolvedValue({ conversation_id: "c1", ...PAGE });

    const page = await fetchConversationPage("c1");

    expect(getMock).toHaveBeenCalledWith("/conversations/c1");
    expect(page.items.map((item) => [item.kind, item.id])).toEqual([
      ["user", "m-3"],
    ]);
    expect([page.state.head, page.cursor]).toEqual([3, 3]);
  });

  it("pages back through the entries route before a seq", async () => {
    getMock.mockResolvedValue(PAGE);

    await fetchEntriesBefore("c 1", 4, 50);

    expect(getMock).toHaveBeenCalledWith(
      "/conversations/c%201/entries?before_seq=4&limit=50",
    );
  });

  it("refuses a payload that is not a page of the log", async () => {
    getMock.mockResolvedValue({ messages: [], has_more: false });

    await expect(fetchConversationPage("c1")).rejects.toThrow();
  });
});

describe("the conversation routes", () => {
  beforeEach(() => {
    postMock.mockReset();
  });

  it("sends a message to the conversation's messages route with the client-minted id", async () => {
    postMock.mockResolvedValue({
      conversation_id: "c/1",
      message_id: "m1",
      seq: 3,
    });

    await sendConversationMessage("c/1", { message_id: "m1", text: "hi" });

    expect(postMock).toHaveBeenCalledWith("/conversations/c%2F1/messages", {
      message_id: "m1",
      text: "hi",
    });
  });

  it("stops through the conversation's stop route", async () => {
    postMock.mockResolvedValue({});

    await stopConversation("c1");

    expect(postMock).toHaveBeenCalledWith("/conversations/c1/stop");
  });
});
