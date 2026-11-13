// @vitest-environment jsdom

import { decidedEnd } from "@shared/utils";
import { describe, expect, it } from "vitest";
import { resolveBatchOutcome } from "@/features/chat/utils/batchOutcome";

const tapped = decidedEnd("approve");
const lost = { approval_id: "a", resolved: false, reason: "not_found" };

describe("resolveBatchOutcome", () => {
  it("prefers how the server says the row ended over the tapped button", () => {
    expect(resolveBatchOutcome({ ...lost, outcome: "denied" }, tapped)).toEqual(
      {
        outcome: "denied",
        decider: null,
        action: null,
      },
    );
    expect(
      resolveBatchOutcome({ ...lost, outcome: "withdrawn" }, tapped).outcome,
    ).toBe("withdrawn");
  });

  it("keeps an approved row's action result beside its outcome", () => {
    expect(
      resolveBatchOutcome(
        { ...lost, outcome: "approved", action: "failed" },
        tapped,
      ),
    ).toEqual({ outcome: "approved", decider: null, action: "failed" });
  });

  it("falls back to the tapped verdict when the server sent nothing", () => {
    expect(resolveBatchOutcome(lost, tapped)).toBe(tapped);
    expect(resolveBatchOutcome({ ...lost, outcome: null }, tapped)).toBe(
      tapped,
    );
  });
});
