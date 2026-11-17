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
  description: {
    action: "Send email",
    headline: "Send email",
    confirm: "send it",
    details: [],
  },
  args_preview: {},
  status: "waiting",
  outcome: null,
  feedback: null,
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
      { status: "approved", decider: "user" },
      "You approved this",
    ],
    [
      "approved by auto mode",
      { status: "approved", decider: "auto" },
      "Matched what you asked for",
    ],
    ["denied", { status: "denied", decider: "user" }, "You declined this"],
    ["expired", { status: "expired" }, "Expired without a response"],
    [
      "cancelled by a Stop",
      { status: "cancelled" },
      "Cancelled before you decided",
    ],
    ["withdrawn", { status: "withdrawn" }, "Agent withdrew this"],
    [
      "approved, then ran",
      { status: "approved", decider: "user", action: "executed" },
      "The approved action ran",
    ],
    [
      "approved, then failed",
      { status: "approved", decider: "user", action: "failed" },
      "Approved, but it didn't go through",
    ],
    [
      "approved, outcome unknown",
      { status: "approved", action: "unknown" },
      "Outcome unknown",
    ],
  ])("%s", (_name, end, line) => {
    expect(approvalOutcomeLabel(card(end))).toBe(line);
  });

  it("auto mode's own reason and the user's denial words win over the defaults", () => {
    expect(
      approvalOutcomeLabel(
        card(
          { status: "approved", decider: "auto" },
          { auto_reason: "you asked" },
        ),
      ),
    ).toBe("you asked");
    expect(
      approvalOutcomeLabel(
        card({ status: "denied" }, { feedback: "wrong person" }),
      ),
    ).toBe("wrong person");
  });

  it("a yes with a change names the change", () => {
    expect(
      approvalOutcomeLabel(
        card({ status: "approved_with_change" }, { feedback: "cc Sam" }),
      ),
    ).toBe("You approved this with a change: cc Sam");
  });

  it("an action that failed after auto mode approved it still says it failed", () => {
    expect(
      approvalOutcomeLabel(
        card({ status: "approved", decider: "auto", action: "failed" }),
      ),
    ).toBe("Approved, but it didn't go through");
  });
});

describe("approvalLabel picks one client's words by the same rule", () => {
  const words: ApprovalLabels<string> = {
    pending: "P",
    autoApproved: "AUTO",
    status: {
      approved: "A",
      approved_with_change: "AC",
      denied: "D",
      expired: "E",
      cancelled: "C",
      withdrawn: "W",
    },
    action: { executing: "X1", executed: "X2", failed: "X3", unknown: "X4" },
  };

  it("pending while waiting, and the action only counts once approved", () => {
    expect(approvalLabel({ status: "waiting" }, words)).toBe("P");
    expect(approvalLabel({ status: "approved", action: "failed" }, words)).toBe(
      "X3",
    );
    expect(approvalLabel({ status: "denied", decider: "auto" }, words)).toBe(
      "D",
    );
    expect(approvalLabel({ status: "approved_with_change" }, words)).toBe("AC");
  });

  it("a card is settled exactly when it no longer waits", () => {
    expect(isSettled({ status: "waiting" })).toBe(false);
    expect(isSettled({ status: "withdrawn" })).toBe(true);
  });
});
