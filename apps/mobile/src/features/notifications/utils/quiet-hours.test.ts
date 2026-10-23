import { describe, expect, it } from "vitest";
import { resolveQuietHoursCommit } from "./quiet-hours";

const saved = { start_hour: 22, end_hour: 7 };

describe("resolveQuietHoursCommit", () => {
  it("saves nothing when the draft matches what is stored", () => {
    expect(resolveQuietHoursCommit(saved, { ...saved })).toEqual({
      kind: "unchanged",
    });
  });

  it("refuses a window that starts and ends on the same hour", () => {
    expect(
      resolveQuietHoursCommit(saved, { start_hour: 7, end_hour: 7 }),
    ).toEqual({ kind: "same-edges" });
  });

  it("saves the whole draft once, with every edge the user moved", () => {
    expect(
      resolveQuietHoursCommit(saved, { start_hour: 23, end_hour: 6 }),
    ).toEqual({ kind: "save", next: { start_hour: 23, end_hour: 6 } });
  });
});
