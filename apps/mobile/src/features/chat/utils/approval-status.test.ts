import type { ApprovalEnd, ApprovalRequestData } from "@gaia/shared/chat";
import { approvalLabel } from "@gaia/shared/chat";
import { describe, expect, it } from "vitest";
import {
  APPROVAL_CHIP_META,
  APPROVAL_RESOLVED_META,
  approvalOutcomeText,
} from "./approval-status";

function card(
  approval_id: string,
  end: Partial<ApprovalEnd> = { status: "waiting" },
): {
  tool_name: string;
  data: ApprovalRequestData;
} {
  return {
    tool_name: "approval_request",
    data: {
      approval_id,
      tool_call_id: `call-${approval_id}`,
      gated_tool_name: "send_email",
      integration_name: "gmail",
      summary: `Send ${approval_id}`,
      args_preview: {},
      status: "waiting",
      outcome: null,
      ...end,
      feedback: null,
      timeout_seconds: 300,
    },
  };
}

const ENDINGS: [string, Partial<ApprovalEnd>, string, string][] = [
  [
    "approved by the user",
    { status: "approved", decider: "user" },
    "Approved",
    "Approved",
  ],
  [
    "approved by auto mode",
    { status: "approved", decider: "auto" },
    "Ran automatically",
    "Auto-approved",
  ],
  ["denied", { status: "denied", decider: "user" }, "Declined", "Denied"],
  ["expired", { status: "expired" }, "Timed out", "Expired"],
  ["cancelled", { status: "cancelled" }, "Cancelled", "Cancelled"],
  ["withdrawn", { status: "withdrawn" }, "Withdrawn", "Withdrawn"],
  [
    "approved, then ran",
    { status: "approved", action: "executed" },
    "Executed",
    "Executed",
  ],
  [
    "approved, then failed",
    { status: "approved", action: "failed" },
    "Failed",
    "Failed",
  ],
  [
    "approved, outcome unknown",
    { status: "approved", action: "unknown" },
    "Unknown",
    "Unknown",
  ],
];

describe("resolved card and activity chip labels", () => {
  it.each(ENDINGS)("%s", (_name, end, cardLabel, chipLabel) => {
    const facts: ApprovalEnd = { status: "waiting", ...end };
    expect(approvalLabel(facts, APPROVAL_RESOLVED_META)?.label).toBe(cardLabel);
    expect(approvalLabel(facts, APPROVAL_CHIP_META)?.label).toBe(chipLabel);
  });

  it("a pending card has no resolved label", () => {
    expect(
      approvalLabel({ status: "waiting" }, APPROVAL_RESOLVED_META),
    ).toBeNull();
    expect(approvalLabel({ status: "waiting" }, APPROVAL_CHIP_META)).toBeNull();
  });
});

describe("approvalOutcomeText", () => {
  it("says an approved action that failed did not go through", () => {
    const { data } = card("ap_1", {
      status: "approved",
      decider: "user",
      action: "failed",
    });
    expect(approvalOutcomeText(data)).toBe(
      "Approved, but it didn't go through",
    );
  });

  it("prefers the user's own denial words", () => {
    const { data } = card("ap_1", { status: "denied", decider: "user" });
    expect(approvalOutcomeText({ ...data, feedback: "wrong person" })).toBe(
      "wrong person",
    );
  });
});
