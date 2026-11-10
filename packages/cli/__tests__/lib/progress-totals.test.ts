import { describe, expect, it } from "vitest";
import { formatByteProgress } from "../../src/lib/byte-size.js";
import { createEtaTracker, formatEta } from "../../src/lib/eta.js";
import { progressCaption } from "../../src/lib/progress.js";

describe("formatByteProgress", () => {
  it("shows done and total in the total's unit", () => {
    expect(formatByteProgress(410e6, 660e6, false)).toBe("410 / 660 MB");
    expect(formatByteProgress(400e6, 1.3e9, false)).toBe("0.4 / 1.3 GB");
  });

  it("marks a total that is still an estimate", () => {
    expect(formatByteProgress(31e6, 72e6, true)).toBe("31 / ~72 MB");
  });

  it("shows a small download in kilobytes rather than as 0 MB", () => {
    expect(formatByteProgress(12_000, 24_000, false)).toBe("12 / 24 KB");
  });
});

describe("createEtaTracker", () => {
  it("has no estimate until it has seen bytes move for a while", () => {
    let now = 0;
    const eta = createEtaTracker(() => now);
    expect(eta.update(0, 100e6)).toBeNull();
    now = 500;
    expect(eta.update(5e6, 100e6)).toBeNull();
  });

  it("estimates the time left from the recent rate", () => {
    let now = 0;
    const eta = createEtaTracker(() => now);
    eta.update(0, 100e6);
    for (let s = 1; s <= 10; s++) {
      now = s * 1000;
      eta.update(s * 5e6, 100e6);
    }
    // 50 MB left at 5 MB/s.
    expect(eta.update(50e6, 100e6)).toBe(10_000);
  });

  it("follows a rate that changes instead of the whole run's average", () => {
    let now = 0;
    const eta = createEtaTracker(() => now);
    eta.update(0, 200e6);
    for (let s = 1; s <= 10; s++) {
      now = s * 1000;
      eta.update(s * 1e6, 200e6);
    }
    for (let s = 11; s <= 30; s++) {
      now = s * 1000;
      eta.update(10e6 + (s - 10) * 5e6, 200e6);
    }
    // 90 MB left at the recent 5 MB/s, not the run's ~3.7 MB/s.
    expect(eta.update(110e6, 200e6)).toBe(18_000);
  });
});

describe("progressCaption", () => {
  it("never shows a percentage without what it is a percentage of", () => {
    expect(
      progressCaption(
        { done: 410e6, total: 660e6, unit: "bytes", estimated: false },
        { etaMs: 70_000 },
      ),
    ).toBe("62%  410 / 660 MB · about 1 min left");
    expect(
      progressCaption({
        done: 7,
        total: 9,
        unit: "services",
        estimated: false,
      }),
    ).toBe("77%  7 / 9 services");
  });

  it("keeps the bar's own position when it is not simply done / total", () => {
    expect(
      progressCaption(
        { done: 5e6, total: 10e6, unit: "bytes", estimated: true },
        { percent: 60 },
      ),
    ).toBe("60%  5 / ~10 MB");
  });
});

describe("formatEta", () => {
  it("rounds to what a person can use", () => {
    expect(formatEta(20_000)).toBe("less than a minute left");
    expect(formatEta(70_000)).toBe("about 1 min left");
    expect(formatEta(9 * 60_000 + 40_000)).toBe("about 10 min left");
    expect(formatEta(2 * 3_600_000)).toBe("about 2 h left");
  });
});
