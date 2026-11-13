import type { ApprovalRequestData, ApprovalStatus } from "@gaia/shared/chat";
import { describe, expect, it } from "vitest";
import {
  APPROVAL_CHIP_META,
  APPROVAL_RESOLVED_META,
  approvalOutcomeText,
} from "./approval-status";

describe("APPROVAL_RESOLVED_META — ledger-terminal crash guard", () => {
  it("covers every non-pending status so the card never derefs undefined", () => {
    const statuses: Exclude<ApprovalStatus, "pending">[] = [
      "approved",
      "denied",
      "timeout",
      "abandoned",
      "auto_approved",
      "revoked",
      "executed",
      "failed",
      "unknown",
    ];
    for (const status of statuses) {
      expect(APPROVAL_RESOLVED_META[status]).toBeDefined();
      expect(APPROVAL_RESOLVED_META[status].label.length).toBeGreaterThan(0);
    }
  });

  it("matches web SubagentRow chip labels for ledger states", () => {
    expect(APPROVAL_RESOLVED_META.executed.label).toBe("Executed");
    expect(APPROVAL_RESOLVED_META.failed.label).toBe("Failed");
    expect(APPROVAL_RESOLVED_META.unknown.label).toBe("Unknown");
  });
});

describe("APPROVAL_CHIP_META — activity row chips", () => {
  it("renders a chip for every ledger-terminal state instead of null", () => {
    expect(APPROVAL_CHIP_META.executed.label).toBe("Executed");
    expect(APPROVAL_CHIP_META.failed.label).toBe("Failed");
    expect(APPROVAL_CHIP_META.unknown.label).toBe("Unknown");
    expect(APPROVAL_CHIP_META.revoked.label.length).toBeGreaterThan(0);
    expect(APPROVAL_CHIP_META.approved.label).toBe("Approved");
  });
});

describe("approvalOutcomeText — libs fallback", () => {
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

  it.each(["executed", "failed", "unknown"] as const)(
    "returns a non-empty line for %s (shared returns '')",
    (status) => {
      const text = approvalOutcomeText({ ...base, status });
      expect(text.trim().length).toBeGreaterThan(0);
    },
  );

  it("prefers explicit feedback when present", () => {
    const text = approvalOutcomeText({
      ...base,
      status: "executed",
      feedback: "Sent message abc",
    });
    expect(text).toContain("Sent message abc");
  });
});
