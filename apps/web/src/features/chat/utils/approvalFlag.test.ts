import { describe, expect, it } from "vitest";

import {
  type ApprovalFlagRow,
  apiRowAwaitsApproval,
  isApprovalFlagStale,
} from "./approvalFlag";

describe("apiRowAwaitsApproval", () => {
  it("lights only on an explicit true", () => {
    expect(apiRowAwaitsApproval({ awaiting_approval: true })).toBe(true);
  });

  it("stays dark on false, missing, null, and undefined rows", () => {
    expect(apiRowAwaitsApproval({ awaiting_approval: false })).toBe(false);
    expect(apiRowAwaitsApproval({})).toBe(false);
    expect(apiRowAwaitsApproval(null)).toBe(false);
    expect(apiRowAwaitsApproval(undefined)).toBe(false);
  });

  it("stays dark on runtime garbage — strict true survives untyped JSON", () => {
    expect(
      apiRowAwaitsApproval({
        awaiting_approval: 1,
      } as unknown as ApprovalFlagRow),
    ).toBe(false);
    expect(
      apiRowAwaitsApproval({
        awaiting_approval: "yes",
      } as unknown as ApprovalFlagRow),
    ).toBe(false);
  });
});

describe("isApprovalFlagStale", () => {
  it("refetches when the server gained a flag the cache lacks", () => {
    expect(isApprovalFlagStale(undefined, { awaiting_approval: true })).toBe(
      true,
    );
    expect(isApprovalFlagStale(false, { awaiting_approval: true })).toBe(true);
  });

  it("refetches when the server cleared a flag the cache holds", () => {
    expect(isApprovalFlagStale(true, { awaiting_approval: false })).toBe(true);
    expect(isApprovalFlagStale(true, {})).toBe(true);
  });

  it("leaves matching rows alone", () => {
    expect(isApprovalFlagStale(true, { awaiting_approval: true })).toBe(false);
    expect(isApprovalFlagStale(false, {})).toBe(false);
    expect(isApprovalFlagStale(undefined, {})).toBe(false);
  });
});
