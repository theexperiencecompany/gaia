import { describe, expect, it } from "vitest";

import { stampSheet } from "./stampSheet";

describe("stampSheet", () => {
  it("lays one row of blanks when nothing is collected, the last counting the rest", () => {
    expect(stampSheet(0, 85, 5)).toEqual({ blanks: 5, lastCounts: 81 });
  });

  it("finishes the row a single stamp starts", () => {
    expect(stampSheet(1, 85, 5)).toEqual({ blanks: 4, lastCounts: 81 });
  });

  it("adds exactly one full row when the stamps fill theirs", () => {
    expect(stampSheet(5, 85, 5)).toEqual({ blanks: 5, lastCounts: 76 });
  });

  it("finishes the second row a stamp past a full row starts", () => {
    expect(stampSheet(6, 85, 5)).toEqual({ blanks: 4, lastCounts: 76 });
  });

  it("leaves no blank once every city is collected", () => {
    expect(stampSheet(85, 85, 5)).toEqual({ blanks: 0, lastCounts: null });
  });

  it("draws each remaining city as its own blank when they fit the row", () => {
    expect(stampSheet(82, 85, 5)).toEqual({ blanks: 3, lastCounts: null });
  });

  it("follows the grid's own column count", () => {
    expect(stampSheet(5, 85, 3)).toEqual({ blanks: 1, lastCounts: 80 });
    expect(stampSheet(5, 85, 4)).toEqual({ blanks: 3, lastCounts: 78 });
  });

  it("adds up to the total at every column count", () => {
    for (const columns of [3, 4, 5, 6]) {
      for (const collected of [0, 1, columns, columns + 1, 84]) {
        const { blanks, lastCounts } = stampSheet(collected, 85, columns);
        expect(collected + blanks - 1 + (lastCounts ?? 1)).toBe(85);
        if (collected + blanks < 85) {
          expect((collected + blanks) % columns).toBe(0);
        }
      }
    }
  });
});
