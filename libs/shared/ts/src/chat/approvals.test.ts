import { describe, expect, it } from "vitest";
import { approvalOutcomeLabel, isSettled } from "./approvals";
import type { ApprovalRequestData } from "./approvals.types";

const base: ApprovalRequestData = {
  approval_id: "ap_1",
  tool_call_id: "call-1",
  gated_tool_name: "send_email",
  integration_name: "gmail",
  summary: "Send email",
  args_preview: {},
  status: "pending",
  feedback: null,
  timeout_seconds: 300,
};

describe("ledger-extended approval shapes", () => {
  it("revoked is settled with a withdraw label", () => {
    expect(isSettled("revoked")).toBe(true);
    expect(approvalOutcomeLabel({ ...base, status: "revoked" })).toBe(
      "Agent withdrew this",
    );
  });

  it("ledger-only fields ride optional without breaking the base shape", () => {
    const card: ApprovalRequestData = {
      ...base,
      rationale: "user asked for cleanup",
      age_seconds: 172800,
      ledger_version: 4,
    };
    expect(card.ledger_version).toBe(4);
  });

  it("decision payloads carry the rendered row version", () => {
    const payload = { decision: "approve" as const, v: 4 };
    expect(payload.v).toBe(4);
  });
});

describe("formatApprovalAge", () => {
  it("renders compact age strings", async () => {
    const { formatApprovalAge } = await import("./approvals");
    expect(formatApprovalAge(30)).toBe("asked just now");
    expect(formatApprovalAge(3600)).toBe("asked 1h ago");
    expect(formatApprovalAge(172800)).toBe("asked 2d ago");
  });

  it("re-confirm threshold is one day", async () => {
    const { RECONFIRM_AGE_SECONDS } = await import("./approvals");
    expect(RECONFIRM_AGE_SECONDS).toBe(86400);
  });
});
