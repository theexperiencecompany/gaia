import { ApiError } from "@gaia/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { postApprovalDecision } from "./chat-api";

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@gaia/shared")>("@gaia/shared");
  return {
    ApiError: actual.ApiError,
    apiService: { post: postMock },
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
