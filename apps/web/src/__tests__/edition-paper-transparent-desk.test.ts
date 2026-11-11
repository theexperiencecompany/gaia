// @vitest-environment jsdom
/**
 * An edition rendered on a transparent desk: the sheet is found by its alpha,
 * so a dark paper is not mistaken for the (black, fully clear) desk around it.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { findPaper } from "@/features/briefing/utils/paperBounds";

const SAMPLE = 240;
const MARGIN = 20;
const INK_DARK_PAPER = 24;

/** A dark opaque sheet inset MARGIN sample pixels on a fully transparent desk. */
function transparentDeskPixels(width: number, height: number) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = MARGIN; y < height - MARGIN; y += 1) {
    for (let x = MARGIN; x < width - MARGIN; x += 1) {
      const index = (y * width + x) * 4;
      data.set([INK_DARK_PAPER, INK_DARK_PAPER, INK_DARK_PAPER, 255], index);
    }
  }
  return data;
}

describe("edition paper on a transparent desk", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("finds a dark sheet inside its clear desk", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: () => undefined,
      getImageData: (
        _x: number,
        _y: number,
        width: number,
        height: number,
      ) => ({
        data: transparentDeskPixels(width, height),
      }),
    } as unknown as CanvasRenderingContext2D);

    const sheet = findPaper({
      source: document.createElement("canvas"),
      width: SAMPLE,
      height: SAMPLE * 2,
    });

    expect(sheet.x).toBeGreaterThanOrEqual(MARGIN);
    expect(sheet.y).toBeGreaterThanOrEqual(MARGIN);
    expect(sheet.width).toBeLessThanOrEqual(SAMPLE - 2 * MARGIN);
    expect(sheet.height).toBeLessThanOrEqual(SAMPLE * 2 - 2 * MARGIN);
  });
});
