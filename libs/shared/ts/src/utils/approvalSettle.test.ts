import { describe, expect, it } from "vitest";
import {
  parseApprovalDecidedEvent,
  settleApprovalToolData,
  statusAfterDecision,
  TERMINAL_APPROVAL_STATUSES,
} from "./approvalSettle";

const frame = (data: Record<string, unknown>) => ({
  type: "hil_approval_decided",
  data,
});

const approval = (approvalId: string, status = "pending") => ({
  tool_name: "approval_request",
  data: { approval_id: approvalId, status, feedback: null },
});

describe("parseApprovalDecidedEvent", () => {
  it("reads the backend's nested envelope", () => {
    expect(
      parseApprovalDecidedEvent(
        frame({
          conversation_id: "c1",
          approval_id: "ap_1",
          status: "approved",
          feedback: "",
          version: 3,
        }),
      ),
    ).toEqual({
      conversation_id: "c1",
      approval_id: "ap_1",
      status: "approved",
      feedback: null,
    });
  });

  it("rejects a frame without the data envelope", () => {
    expect(
      parseApprovalDecidedEvent({
        type: "hil_approval_decided",
        conversation_id: "c1",
        approval_id: "ap_1",
        status: "approved",
      }),
    ).toBeNull();
  });

  it("treats every ledger-terminal state as terminal", () => {
    expect([...TERMINAL_APPROVAL_STATUSES].sort()).toEqual(
      ["approved", "denied", "executed", "failed", "revoked", "unknown"].sort(),
    );
  });

  it("ignores a non-terminal status", () => {
    expect(
      parseApprovalDecidedEvent(
        frame({
          conversation_id: "c1",
          approval_id: "ap_1",
          status: "pending",
        }),
      ),
    ).toBeNull();
  });
});

describe("statusAfterDecision", () => {
  it("settles to the user's own verdict when the commit landed", () => {
    expect(statusAfterDecision("approve", { success: true })).toBe("approved");
    expect(statusAfterDecision("deny", { success: true })).toBe("denied");
  });

  it("settles to the verdict another device already committed", () => {
    expect(
      statusAfterDecision("approve", { success: false, status: "denied" }),
    ).toBe("denied");
  });

  it("asks for a retry when the refusal names no settled verdict", () => {
    expect(
      statusAfterDecision("approve", { success: false, reason: "not_found" }),
    ).toBeNull();
    expect(
      statusAfterDecision("approve", { success: false, status: "pending" }),
    ).toBeNull();
    expect(
      statusAfterDecision("approve", { success: false, status: "unknown" }),
    ).toBeNull();
    expect(
      statusAfterDecision("approve", { success: false, status: "bogus" }),
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
      { approval_id: "ap_1", status: "revoked", feedback: null },
    );
    expect(changed).toBe(true);
    expect(entries?.[0]).toBe(other);
    expect(entries?.[1]?.data).toMatchObject({ status: "revoked" });
    expect(entries?.[2]).toBe(sibling);
  });

  it("returns the input by identity when nothing matched", () => {
    const input = [approval("ap_2")];
    const result = settleApprovalToolData(input, {
      approval_id: "ap_1",
      status: "approved",
      feedback: null,
    });
    expect(result).toEqual({ entries: input, changed: false });
    expect(result.entries).toBe(input);
  });
});
