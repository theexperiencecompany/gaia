// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { resolveBatchOutcomeStatus } from "@/features/chat/utils/batchOutcome";

describe("resolveBatchOutcomeStatus", () => {
  it("prefers the server state over the tapped button", () => {
    expect(resolveBatchOutcomeStatus("denied", "approved")).toBe("denied");
    expect(resolveBatchOutcomeStatus("revoked", "approved")).toBe("revoked");
    expect(resolveBatchOutcomeStatus("executed", "approved")).toBe("executed");
  });

  it("falls back to the tapped verdict when the server sent nothing", () => {
    expect(resolveBatchOutcomeStatus(null, "approved")).toBe("approved");
    expect(resolveBatchOutcomeStatus(undefined, "denied")).toBe("denied");
  });

  it("falls back on unknown server states instead of painting garbage", () => {
    expect(resolveBatchOutcomeStatus("executing", "approved")).toBe("approved");
  });
});
