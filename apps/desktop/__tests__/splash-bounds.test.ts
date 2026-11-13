/**
 * Tests for the boot-loader sizing (splash + main window start bounds).
 *
 * The loader must fit on every screen: large enough that the shell skeleton
 * is legible, small enough to read as a loader, and never larger than the
 * display's work area. A size that overflows the work area would open
 * off-screen or force an immediate resize — the exact "weird window" class of
 * bug that only surfaces on a display the developer doesn't own.
 */

import { describe, expect, it } from "vitest";
import {
  resolveLoaderSize,
  resolveNormalBounds,
} from "../src/main/windows/loader-geometry";

function expectFits(
  workArea: { width: number; height: number },
  size: { width: number; height: number },
): void {
  expect(size.width).toBeLessThanOrEqual(workArea.width);
  expect(size.height).toBeLessThanOrEqual(workArea.height);
  expect(size.width).toBeGreaterThan(0);
  expect(size.height).toBeGreaterThan(0);
}

describe("resolveLoaderSize", () => {
  it("sizes to 72% of a 13-inch MacBook work area", () => {
    // 1710×1107 (14" MacBook Pro, more space) — the display this was tuned on.
    const size = resolveLoaderSize({ width: 1710, height: 1107 });
    expect(size).toEqual({ width: 1231, height: 797 });
    expectFits({ width: 1710, height: 1107 }, size);
  });

  it("caps at the maximum on a 1080p display", () => {
    const size = resolveLoaderSize({ width: 1920, height: 1040 });
    expect(size).toEqual({ width: 1280, height: 749 });
    expectFits({ width: 1920, height: 1040 }, size);
  });

  it("caps at the maximum on a 4K display", () => {
    const size = resolveLoaderSize({ width: 3840, height: 2110 });
    expect(size).toEqual({ width: 1280, height: 820 });
    expectFits({ width: 3840, height: 2110 }, size);
  });

  it("floors at the minimum on a small 1280×800 laptop panel", () => {
    const size = resolveLoaderSize({ width: 1280, height: 772 });
    expect(size).toEqual({ width: 922, height: 600 });
    expectFits({ width: 1280, height: 772 }, size);
  });

  it("never overflows a tiny 1024×640 panel", () => {
    const workArea = { width: 1024, height: 612 };
    const size = resolveLoaderSize(workArea);
    expect(size).toEqual({ width: 880, height: 600 });
    expectFits(workArea, size);
  });

  it("never overflows an extreme 800×600 panel", () => {
    const workArea = { width: 800, height: 572 };
    const size = resolveLoaderSize(workArea);
    expectFits(workArea, size);
  });
});

describe("resolveNormalBounds", () => {
  it("centers the 1400×900 normal frame on a large display", () => {
    const bounds = resolveNormalBounds({
      x: 0,
      y: 25,
      width: 1920,
      height: 1040,
    });
    expect(bounds).toEqual({ x: 260, y: 95, width: 1400, height: 900 });
  });

  it("shrinks to the work area on a panel smaller than the normal frame", () => {
    const bounds = resolveNormalBounds({
      x: 0,
      y: 0,
      width: 1024,
      height: 640,
    });
    expect(bounds).toEqual({ x: 0, y: 0, width: 1024, height: 640 });
  });
});
