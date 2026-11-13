import { describe, expect, it } from "vitest";
import {
  approvalAgeSeconds,
  approvalExpiresAt,
  approvalOutcomeLabel,
  cardDescription,
  formatApprovalAge,
  isSettled,
  settleCard,
} from "./approvals";
import type { ApprovalRequestData } from "./approvals.types";

const base: ApprovalRequestData = {
  approval_id: "ap_1",
  tool_call_id: "call-1",
  gated_tool_name: "send_email",
  integration_name: "gmail",
  summary: "Send an email",
  description: {
    action: "Send an email",
    headline: "Send an email",
    confirm: "send it",
    details: [],
  },
  args_preview: {},
  status: "pending",
  feedback: null,
  auto_reason: null,
  asked_at: "2026-11-10T10:00:00Z",
};

describe("approval outcomes", () => {
  it("names who withdrew a card: the agent, or the user's Stop", () => {
    expect(isSettled("revoked")).toBe(true);
    expect(approvalOutcomeLabel({ ...base, status: "revoked" })).toBe(
      "GAIA withdrew this request, so nothing was done",
    );
    expect(approvalOutcomeLabel({ ...base, status: "cancelled" })).toBe(
      "You stopped GAIA before answering, so nothing was done",
    );
  });

  it("says what is known when the result could not be confirmed", () => {
    expect(approvalOutcomeLabel({ ...base, status: "unknown" })).toBe(
      "You approved this, but GAIA couldn't confirm it went through",
    );
  });
});

describe("card age", () => {
  const now = Date.parse("2026-11-12T10:00:00Z");

  it("is computed from when the card was asked, at render time", () => {
    expect(approvalAgeSeconds(base, now)).toBe(172800);
  });

  it("is unknown on a card saved before asked_at existed", () => {
    expect(
      approvalAgeSeconds({ asked_at: undefined } as never, now),
    ).toBeNull();
  });

  it("reads as words", () => {
    expect(formatApprovalAge(30)).toBe("just now");
    expect(formatApprovalAge(3600)).toBe("1h ago");
    expect(formatApprovalAge(172800)).toBe("2d ago");
  });
});

describe("card shape", () => {
  it("settling drops an expiry, so a decided card never claims to expire", () => {
    const expiring: ApprovalRequestData = {
      ...base,
      expires_at: "2026-11-12T16:00:00Z",
    };
    expect(approvalExpiresAt(expiring)).toBe("2026-11-12T16:00:00Z");
    const settled = settleCard(expiring, "approved", null);
    expect(settled).not.toHaveProperty("expires_at");
    expect(approvalExpiresAt(settled)).toBeNull();
  });

  it("a card saved before descriptions reads as its summary", () => {
    expect(
      cardDescription({ summary: "Gmail send email", description: undefined }),
    ).toEqual({
      action: "Gmail send email",
      headline: "Gmail send email",
      confirm: "go ahead",
      details: [],
    });
  });
});
