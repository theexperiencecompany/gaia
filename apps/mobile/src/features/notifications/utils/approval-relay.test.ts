import { beforeEach, describe, expect, it, vi } from "vitest";

const postApprovalDecision = vi.fn();
vi.mock("@/features/chat/api/chat-api", () => ({
  chatApi: { postApprovalDecision },
}));

const { APPROVAL_ALREADY_HANDLED, APPROVAL_NOT_SENT, relayApprovalDecision } =
  await import("./approval-relay");

describe("relayApprovalDecision", () => {
  beforeEach(() => {
    postApprovalDecision.mockReset();
  });

  it("stays quiet when the decision committed", async () => {
    postApprovalDecision.mockResolvedValue({ success: true });

    expect(await relayApprovalDecision("ap_1", "approve")).toBeNull();
    expect(postApprovalDecision).toHaveBeenCalledWith("ap_1", {
      decision: "approve",
    });
  });

  it("says so when another device already settled it", async () => {
    postApprovalDecision.mockResolvedValue({
      success: false,
      status: "denied",
    });

    expect(await relayApprovalDecision("ap_1", "approve")).toBe(
      APPROVAL_ALREADY_HANDLED,
    );
  });

  it("says so when the approval is already gone", async () => {
    postApprovalDecision.mockResolvedValue({
      success: false,
      reason: "not_found",
    });

    expect(await relayApprovalDecision("ap_1", "deny")).toBe(
      APPROVAL_ALREADY_HANDLED,
    );
  });

  it("tells the user to retry when the request failed", async () => {
    postApprovalDecision.mockRejectedValue(new Error("network down"));

    expect(await relayApprovalDecision("ap_1", "approve")).toBe(
      APPROVAL_NOT_SENT,
    );
  });
});
