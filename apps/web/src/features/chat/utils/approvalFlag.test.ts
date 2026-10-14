import { describe, expect, it } from "vitest";

import {
  type ApprovalFlagRow,
  apiRowHasLiveApproval,
  isApprovalFlagStale,
} from "./approvalFlag";

describe("apiRowHasLiveApproval", () => {
  it("lights only on an explicit true", () => {
    expect(apiRowHasLiveApproval({ has_live_approval: true })).toBe(true);
  });

  it("stays dark on false, missing, null, and undefined rows", () => {
    expect(apiRowHasLiveApproval({ has_live_approval: false })).toBe(false);
    expect(apiRowHasLiveApproval({})).toBe(false);
    expect(apiRowHasLiveApproval({ has_live_approval: null })).toBe(false);
    expect(apiRowHasLiveApproval(null)).toBe(false);
    expect(apiRowHasLiveApproval(undefined)).toBe(false);
  });

  it("stays dark on runtime garbage — strict true survives untyped JSON", () => {
    expect(
      apiRowHasLiveApproval({
        has_live_approval: 1,
      } as unknown as ApprovalFlagRow),
    ).toBe(false);
    expect(
      apiRowHasLiveApproval({
        has_live_approval: "yes",
      } as unknown as ApprovalFlagRow),
    ).toBe(false);
  });
});

describe("isApprovalFlagStale", () => {
  it("refetches when the server gained a flag the cache lacks", () => {
    expect(isApprovalFlagStale(undefined, { has_live_approval: true })).toBe(
      true,
    );
    expect(isApprovalFlagStale(false, { has_live_approval: true })).toBe(true);
  });

  it("refetches when the server cleared a flag the cache holds", () => {
    expect(isApprovalFlagStale(true, { has_live_approval: false })).toBe(true);
    expect(isApprovalFlagStale(true, {})).toBe(true);
  });

  it("leaves matching rows alone", () => {
    expect(isApprovalFlagStale(true, { has_live_approval: true })).toBe(false);
    expect(isApprovalFlagStale(false, {})).toBe(false);
    expect(isApprovalFlagStale(undefined, {})).toBe(false);
  });
});
