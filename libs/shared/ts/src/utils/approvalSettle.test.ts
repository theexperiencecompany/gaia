import { describe, expect, it } from "vitest";
import { decidedEnd, endAfterDecision } from "./approvalSettle";

describe("endAfterDecision", () => {
  it("settles to the user's own verdict when the commit landed", () => {
    expect(endAfterDecision("approve", { success: true })).toEqual(
      decidedEnd("approve"),
    );
    expect(endAfterDecision("deny", { success: true })).toEqual({
      status: "denied",
      decider: "user",
      action: null,
    });
  });

  it("settles to what another device already committed, with its action", () => {
    expect(
      endAfterDecision("approve", { success: false, outcome: "denied" }),
    ).toEqual({
      status: "denied",
      decider: null,
      action: null,
    });
    expect(
      endAfterDecision("deny", {
        success: false,
        outcome: "approved",
        action: "unknown",
      }),
    ).toEqual({ status: "approved", decider: null, action: "unknown" });
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
