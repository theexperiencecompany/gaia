import { describe, expect, it } from "vitest";
import {
  decidedEnd,
  endAfterDecision,
  parseApprovalDecidedEvent,
  settleApprovalToolData,
} from "./approvalSettle";

const frame = (data: Record<string, unknown>) => ({
  type: "hil_approval_decided",
  data,
});

const approval = (approvalId: string) => ({
  tool_name: "approval_request",
  data: { approval_id: approvalId, outcome: null, feedback: null },
});

describe("parseApprovalDecidedEvent", () => {
  it("reads the backend's nested envelope", () => {
    expect(
      parseApprovalDecidedEvent(
        frame({
          conversation_id: "c1",
          approval_id: "ap_1",
          outcome: "approved",
          decider: "user",
          action: null,
          feedback: "",
          version: 3,
        }),
      ),
    ).toEqual({
      conversation_id: "c1",
      approval_id: "ap_1",
      outcome: "approved",
      decider: "user",
      action: null,
      feedback: null,
    });
  });

  it("carries an approved action's result beside the approval", () => {
    expect(
      parseApprovalDecidedEvent(
        frame({
          conversation_id: "c1",
          approval_id: "ap_1",
          outcome: "approved",
          action: "failed",
        }),
      ),
    ).toMatchObject({ outcome: "approved", action: "failed" });
  });

  it("rejects a frame without the data envelope", () => {
    expect(
      parseApprovalDecidedEvent({
        type: "hil_approval_decided",
        conversation_id: "c1",
        approval_id: "ap_1",
        outcome: "approved",
      }),
    ).toBeNull();
  });

  it.each(["withdrawn", "cancelled", "expired", "denied"])(
    "settles a card %s",
    (outcome) => {
      expect(
        parseApprovalDecidedEvent(
          frame({ conversation_id: "c1", approval_id: "ap_1", outcome }),
        ),
      ).toMatchObject({ outcome, decider: null, action: null });
    },
  );

  it("ignores a frame naming no outcome, or a word from the old vocabulary", () => {
    for (const outcome of [undefined, null, "pending", "revoked", "timeout"]) {
      expect(
        parseApprovalDecidedEvent(
          frame({ conversation_id: "c1", approval_id: "ap_1", outcome }),
        ),
      ).toBeNull();
    }
  });
});

describe("endAfterDecision", () => {
  it("settles to the user's own verdict when the commit landed", () => {
    expect(endAfterDecision("approve", { success: true })).toEqual(
      decidedEnd("approve"),
    );
    expect(endAfterDecision("deny", { success: true })).toEqual({
      outcome: "denied",
      decider: "user",
      action: null,
    });
  });

  it("settles to what another device already committed, with its action", () => {
    expect(
      endAfterDecision("approve", { success: false, outcome: "denied" }),
    ).toEqual({
      outcome: "denied",
      decider: null,
      action: null,
    });
    expect(
      endAfterDecision("deny", {
        success: false,
        outcome: "approved",
        action: "unknown",
      }),
    ).toEqual({ outcome: "approved", decider: null, action: "unknown" });
  });

  it("asks for a retry when the refusal names no outcome", () => {
    expect(
      endAfterDecision("approve", { success: false, reason: "not_found" }),
    ).toBeNull();
    expect(
      endAfterDecision("approve", { success: false, outcome: null }),
    ).toBeNull();
  });
});

describe("settleApprovalToolData", () => {
  it("flips only the matching approval and keeps the rest by identity", () => {
    const other = { tool_name: "search", data: { approval_id: "ap_1" } };
    const target = approval("ap_1");
    const sibling = approval("ap_2");
    const { entries, changed } = settleApprovalToolData(
      [other, target, sibling],
      {
        approval_id: "ap_1",
        outcome: "approved",
        decider: "user",
        action: "failed",
        feedback: null,
      },
    );
    expect(changed).toBe(true);
    expect(entries?.[0]).toBe(other);
    expect(entries?.[1]?.data).toMatchObject({
      outcome: "approved",
      decider: "user",
      action: "failed",
    });
    expect(entries?.[2]).toBe(sibling);
  });

  it("returns the input by identity when nothing matched", () => {
    const input = [approval("ap_2")];
    const result = settleApprovalToolData(input, {
      approval_id: "ap_1",
      outcome: "approved",
      feedback: null,
    });
    expect(result).toEqual({ entries: input, changed: false });
    expect(result.entries).toBe(input);
  });
});
