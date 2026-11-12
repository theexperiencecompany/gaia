import { ApiError } from "@gaia/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchConversation,
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

describe("fetchConversation", () => {
  it("carries what woke a tracked todo's run onto its user message", async () => {
    const wake = {
      kind: "schedule",
      trigger_names: [],
      approval_summary: null,
    };
    getMock.mockResolvedValue({
      _id: "c",
      user_id: "u",
      conversation_id: "todo-chat",
      description: "Watch the staging deploy",
      is_system_generated: true,
      system_purpose: null,
      is_unread: false,
      createdAt: "2026-10-31T14:05:00Z",
      messages: [
        {
          type: "user",
          response: "",
          date: "2026-10-31T14:05:00Z",
          message_id: "m-1",
          fileIds: [],
          fileData: [],
          todo_run_wake: wake,
        },
      ],
    });

    const conversation = await fetchConversation("todo-chat");

    expect(conversation?.messages[0]?.todoRunWake).toEqual(wake);
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

  it("keeps the reaction the history carries on its message", async () => {
    getMock.mockResolvedValue({
      _id: "c",
      user_id: "u",
      conversation_id: "c1",
      description: "",
      is_system_generated: false,
      system_purpose: null,
      is_unread: false,
      createdAt: "2026-10-31T14:05:00Z",
      messages: [
        {
          type: "user",
          response: "thanks",
          date: "2026-10-31T14:05:00Z",
          message_id: "m-1",
          fileIds: [],
          fileData: [],
          reaction: { emoji: "🙌", by: "jev" },
        },
      ],
    });

    const conversation = await fetchConversation("c1");

    expect(conversation?.messages[0]?.reaction).toEqual({
      emoji: "🙌",
      by: "jev",
    });
  });
});
