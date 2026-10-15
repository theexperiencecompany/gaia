import { existsSync, readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import type { Rect } from "./dom";

/**
 * Screenshots of a visual-diff run and the pixel test that decides whether a
 * computed-style change is visible: the base and head crops of an element differ.
 */

export interface Screenshot {
  uri: string;
  width: number;
  height: number;
}

export interface Visibility {
  visible: boolean;
  changedPixels: number;
}

/** The element's rect on each side; an element present on one side only uses its rect on both. */
export interface RectPair {
  base: Rect;
  head: Rect;
}

interface CropComparison {
  sameSize: boolean;
  area: number;
  changedPixels: number;
}

// A channel delta at or below this is antialiasing or compression noise.
const CHANNEL_TOLERANCE = 8;
const VISIBLE_SHARE = 0.005;
const VISIBLE_MIN_PIXELS = 20;

// PNG stores width and height as big-endian uint32s at bytes 16 and 20.
function pngSize(path: string): { width: number; height: number } {
  const header = readFileSync(path).subarray(16, 24);
  return { width: header.readUInt32BE(0), height: header.readUInt32BE(4) };
}

export function loadScreenshot(path: string): Screenshot {
  if (!existsSync(path)) throw new Error(`screenshot missing: ${path}`);
  return {
    uri: `data:image/png;base64,${readFileSync(path).toString("base64")}`,
    ...pngSize(path),
  };
}

/** Compare each pair's base crop with its head crop, clipped to the screenshots, in the browser. */
async function compareCrops(
  page: Page,
  base: Screenshot,
  head: Screenshot,
  pairs: RectPair[],
): Promise<CropComparison[]> {
  return page.evaluate(
    async ({ baseUri, headUri, pairs, tolerance }) => {
      const pixelsOf = async (uri: string) => {
        const image = new Image();
        image.src = uri;
        await image.decode();
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("2d canvas context unavailable");
        context.drawImage(image, 0, 0);
        return context.getImageData(0, 0, canvas.width, canvas.height);
      };
      const [basePixels, headPixels] = await Promise.all([
        pixelsOf(baseUri),
        pixelsOf(headUri),
      ]);
      const clip = (
        rect: (typeof pairs)[number]["base"],
        pixels: ImageData,
      ) => {
        const x = Math.max(0, rect.x);
        const y = Math.max(0, rect.y);
        return {
          x,
          y,
          width: Math.max(0, Math.min(pixels.width, rect.x + rect.width) - x),
          height: Math.max(
            0,
            Math.min(pixels.height, rect.y + rect.height) - y,
          ),
        };
      };
      return pairs.map((pair) => {
        const from = clip(pair.base, basePixels);
        const to = clip(pair.head, headPixels);
        const width = Math.min(from.width, to.width);
        const height = Math.min(from.height, to.height);
        // Pixels one crop has and the other lacks count as changed.
        let changedPixels =
          Math.max(from.width * from.height, to.width * to.height) -
          width * height;
        for (let row = 0; row < height; row += 1) {
          for (let col = 0; col < width; col += 1) {
            const a = ((from.y + row) * basePixels.width + from.x + col) * 4;
            const b = ((to.y + row) * headPixels.width + to.x + col) * 4;
            for (let channel = 0; channel < 4; channel += 1) {
              const delta =
                basePixels.data[a + channel] - headPixels.data[b + channel];
              if (Math.abs(delta) > tolerance) {
                changedPixels += 1;
                break;
              }
            }
          }
        }
        return {
          sameSize: from.width === to.width && from.height === to.height,
          area: from.width * from.height,
          changedPixels,
        };
      });
    },
    {
      baseUri: base.uri,
      headUri: head.uri,
      pairs,
      tolerance: CHANNEL_TOLERANCE,
    },
  );
}

/** Whether each pair's change shows on screen: its crops differ in size or in enough pixels. */
export async function measureVisibility(
  page: Page,
  base: Screenshot,
  head: Screenshot,
  pairs: RectPair[],
): Promise<Visibility[]> {
  const comparisons = await compareCrops(page, base, head, pairs);
  return comparisons.map(({ sameSize, area, changedPixels }) => ({
    changedPixels,
    visible:
      (!sameSize && changedPixels > 0) ||
      (changedPixels >= VISIBLE_MIN_PIXELS &&
        changedPixels > area * VISIBLE_SHARE),
  }));
}
