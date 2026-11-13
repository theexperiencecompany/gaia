import type { ApprovalEnd, ApprovalRequestData } from "@gaia/shared/chat";
import { approvalLabel } from "@gaia/shared/chat";
import { describe, expect, it } from "vitest";
import type { Message } from "@/features/chat/api/chat-api";
import {
  APPROVAL_CHIP_META,
  APPROVAL_RESOLVED_META,
  applyApprovalDecisionToMessages,
  approvalOutcomeText,
} from "./approval-status";

function card(
  approval_id: string,
  end: Partial<ApprovalEnd> = { outcome: null },
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
      outcome: null,
      ...end,
      feedback: null,
      timeout_seconds: 300,
    },
  };
}

function msg(
  id: string,
  toolData: { tool_name: string; data: unknown }[],
): Message {
  return {
    id,
    text: "hi",
    isUser: false,
    timestamp: new Date("2026-09-19T00:00:00Z"),
    toolData: toolData as Message["toolData"],
  };
}

const ENDINGS: [string, Partial<ApprovalEnd>, string, string][] = [
  [
    "approved by the user",
    { outcome: "approved", decider: "user" },
    "Approved",
    "Approved",
  ],
  [
    "approved by auto mode",
    { outcome: "approved", decider: "auto" },
    "Ran automatically",
    "Auto-approved",
  ],
  ["denied", { outcome: "denied", decider: "user" }, "Declined", "Denied"],
  ["expired", { outcome: "expired" }, "Timed out", "Expired"],
  ["cancelled", { outcome: "cancelled" }, "Cancelled", "Cancelled"],
  ["withdrawn", { outcome: "withdrawn" }, "Withdrawn", "Withdrawn"],
  [
    "approved, then ran",
    { outcome: "approved", action: "executed" },
    "Executed",
    "Executed",
  ],
  [
    "approved, then failed",
    { outcome: "approved", action: "failed" },
    "Failed",
    "Failed",
  ],
  [
    "approved, outcome unknown",
    { outcome: "approved", action: "unknown" },
    "Unknown",
    "Unknown",
  ],
];

describe("resolved card and activity chip labels", () => {
  it.each(ENDINGS)("%s", (_name, end, cardLabel, chipLabel) => {
    const facts = { outcome: null, ...end };
    expect(approvalLabel(facts, APPROVAL_RESOLVED_META)?.label).toBe(cardLabel);
    expect(approvalLabel(facts, APPROVAL_CHIP_META)?.label).toBe(chipLabel);
  });

  it("a pending card has no resolved label", () => {
    expect(approvalLabel({ outcome: null }, APPROVAL_RESOLVED_META)).toBeNull();
    expect(approvalLabel({ outcome: null }, APPROVAL_CHIP_META)).toBeNull();
  });
});

describe("approvalOutcomeText", () => {
  it("says an approved action that failed did not go through", () => {
    const { data } = card("ap_1", {
      outcome: "approved",
      decider: "user",
      action: "failed",
    });
    expect(approvalOutcomeText(data)).toBe(
      "Approved, but it didn't go through",
    );
  });

  it("prefers the user's own denial words", () => {
    const { data } = card("ap_1", { outcome: "denied", decider: "user" });
    expect(approvalOutcomeText({ ...data, feedback: "wrong person" })).toBe(
      "wrong person",
    );
  });
});

describe("applyApprovalDecisionToMessages — hil_approval_decided settle", () => {
  it("flips the matching card and leaves siblings alone", () => {
    const messages = [
      msg("m1", [card("ap_1"), card("ap_2")]),
      msg("m2", [card("ap_3")]),
    ];
    const { messages: next, changed } = applyApprovalDecisionToMessages(
      messages,
      {
        conversation_id: "conv-1",
        approval_id: "ap_1",
        outcome: "approved",
        decider: "user",
        feedback: null,
      },
    );
    expect(changed).toBe(true);
    const outcomes = (next[0].toolData ?? []).map(
      (e) => (e.data as ApprovalRequestData).outcome,
    );
    expect(outcomes).toEqual(["approved", null]);
    const siblingEntries = next[1].toolData ?? [];
    expect((siblingEntries[0].data as ApprovalRequestData).outcome).toBeNull();
  });

  it("settles an approved card's action result beside its outcome", () => {
    const { messages: next } = applyApprovalDecisionToMessages(
      [msg("m1", [card("ap_1")])],
      {
        conversation_id: "conv-1",
        approval_id: "ap_1",
        outcome: "approved",
        action: "failed",
        feedback: "tool exploded",
      },
    );
    const data = next[0].toolData?.[0].data as ApprovalRequestData;
    expect([data.outcome, data.action, data.feedback]).toEqual([
      "approved",
      "failed",
      "tool exploded",
    ]);
  });

  it("is a no-op for unknown ids and never mutates the input", () => {
    const messages = [msg("m1", [card("ap_1")])];
    const { messages: next, changed } = applyApprovalDecisionToMessages(
      messages,
      {
        conversation_id: "conv-1",
        approval_id: "ap_nope",
        outcome: "approved",
        feedback: null,
      },
    );
    expect(changed).toBe(false);
    expect(next).toBe(messages);
  });
});
