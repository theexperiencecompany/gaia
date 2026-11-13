import { describe, expect, it } from "vitest";
import { approvalLabel, approvalOutcomeLabel, isSettled } from "./approvals";
import type {
  ApprovalEnd,
  ApprovalLabels,
  ApprovalRequestData,
} from "./approvals.types";

const base: ApprovalRequestData = {
  approval_id: "ap_1",
  tool_call_id: "call-1",
  gated_tool_name: "send_email",
  integration_name: "gmail",
  summary: "Send email",
  args_preview: {},
  outcome: null,
  feedback: null,
  timeout_seconds: 300,
};

const card = (
  end: Partial<ApprovalEnd>,
  rest: Partial<ApprovalRequestData> = {},
) => ({
  ...base,
  ...end,
  ...rest,
});

describe("approvalOutcomeLabel reads every ending from the card's own facts", () => {
  it.each<[string, Partial<ApprovalEnd>, string]>([
    [
      "approved by the user",
      { outcome: "approved", decider: "user" },
      "You approved this",
    ],
    [
      "approved by auto mode",
      { outcome: "approved", decider: "auto" },
      "Matched what you asked for",
    ],
    ["denied", { outcome: "denied", decider: "user" }, "You declined this"],
    ["expired", { outcome: "expired" }, "Expired without a response"],
    [
      "cancelled by a Stop",
      { outcome: "cancelled" },
      "Cancelled before you decided",
    ],
    ["withdrawn", { outcome: "withdrawn" }, "Agent withdrew this"],
    [
      "approved, then ran",
      { outcome: "approved", decider: "user", action: "executed" },
      "The approved action ran",
    ],
    [
      "approved, then failed",
      { outcome: "approved", decider: "user", action: "failed" },
      "Approved, but it didn't go through",
    ],
    [
      "approved, outcome unknown",
      { outcome: "approved", action: "unknown" },
      "Outcome unknown",
    ],
  ])("%s", (_name, end, line) => {
    expect(approvalOutcomeLabel(card(end))).toBe(line);
  });

  it("auto mode's own reason and the user's denial words win over the defaults", () => {
    expect(
      approvalOutcomeLabel(
        card(
          { outcome: "approved", decider: "auto" },
          { auto_reason: "you asked" },
        ),
      ),
    ).toBe("you asked");
    expect(
      approvalOutcomeLabel(
        card({ outcome: "denied" }, { feedback: "wrong person" }),
      ),
    ).toBe("wrong person");
  });

  it("an action that failed after auto mode approved it still says it failed", () => {
    expect(
      approvalOutcomeLabel(
        card({ outcome: "approved", decider: "auto", action: "failed" }),
      ),
    ).toBe("Approved, but it didn't go through");
  });
});

describe("approvalLabel picks one client's words by the same rule", () => {
  const words: ApprovalLabels<string> = {
    pending: "P",
    autoApproved: "AUTO",
    outcome: {
      approved: "A",
      denied: "D",
      expired: "E",
      cancelled: "C",
      withdrawn: "W",
    },
    action: { executing: "X1", executed: "X2", failed: "X3", unknown: "X4" },
  };

  it("pending until an outcome exists, and the action only counts once approved", () => {
    expect(approvalLabel({ outcome: null }, words)).toBe("P");
    expect(
      approvalLabel({ outcome: "approved", action: "failed" }, words),
    ).toBe("X3");
    expect(approvalLabel({ outcome: "denied", decider: "auto" }, words)).toBe(
      "D",
    );
  });

  it("a card is settled exactly when it has an outcome", () => {
    expect(isSettled({ outcome: null })).toBe(false);
    expect(isSettled({ outcome: "withdrawn" })).toBe(true);
  });
});
