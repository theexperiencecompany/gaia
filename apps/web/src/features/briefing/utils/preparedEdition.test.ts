// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./frontPaper", () => ({ frontPaper: () => [240, 236, 228] }));

interface FakeBitmap {
  width: number;
  height: number;
  close: ReturnType<typeof vi.fn>;
}

const decoded: string[] = [];
const bitmapsBySrc = new Map<string, FakeBitmap[]>();
/** Every rectangle cut from each source, as [x, y, width, height] in its pixels. */
const cutsBySrc = new Map<string, number[][]>();

class FakeImage {
  crossOrigin = "";
  src = "";
  naturalWidth = 1000;
  naturalHeight = 1500;
  decode() {
    decoded.push(this.src);
    return Promise.resolve();
  }
}

function fakeCreateImageBitmap(
  source: FakeImage,
  x: number,
  y: number,
  w: number,
  h: number,
  options: { resizeWidth: number; resizeHeight: number },
): Promise<FakeBitmap> {
  cutsBySrc.set(source.src, [
    ...(cutsBySrc.get(source.src) ?? []),
    [x, y, w, h],
  ]);
  const bitmap = {
    width: options.resizeWidth,
    height: options.resizeHeight,
    close: vi.fn(),
  };
  bitmapsBySrc.set(source.src, [
    ...(bitmapsBySrc.get(source.src) ?? []),
    bitmap,
  ]);
  return Promise.resolve(bitmap);
}

const LAYOUT = { fold: 0.3, paper: [0, 0, 1, 1] };

async function loadModule() {
  vi.resetModules();
  return import("./preparedEdition");
}

function closedCount(src: string): number {
  return (bitmapsBySrc.get(src) ?? []).filter(
    (bitmap) => bitmap.close.mock.calls.length > 0,
  ).length;
}

describe("prepared editions", () => {
  beforeEach(() => {
    decoded.length = 0;
    bitmapsBySrc.clear();
    cutsBySrc.clear();
    vi.stubGlobal("Image", FakeImage);
    vi.stubGlobal("createImageBitmap", fakeCreateImageBitmap);
    window.innerWidth = 1280;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("closes the bitmaps of editions nobody holds once more than a few are kept", async () => {
    const { prepareEdition } = await loadModule();
    const sources = Array.from({ length: 8 }, (_, i) => `https://cdn/${i}.png`);

    for (const src of sources) await prepareEdition(src, LAYOUT);
    await Promise.resolve();

    expect(closedCount(sources[0])).toBeGreaterThan(0);
    expect(closedCount(sources[0])).toBe(bitmapsBySrc.get(sources[0])?.length);
    expect(closedCount(sources[7])).toBe(0);
  });

  it("cuts the sheet at the paper box the API measured, a hair inside it", async () => {
    const { prepareEdition } = await loadModule();

    await prepareEdition("https://cdn/a.png", {
      fold: null,
      paper: [0.1, 0.05, 0.9, 0.95],
    });

    const [sheet] = cutsBySrc.get("https://cdn/a.png") ?? [];
    const inset = 800 * 0.004;
    const expected = [
      100 + inset,
      75 + inset,
      800 - 2 * inset,
      1350 - 2 * inset,
    ];
    expected.forEach((value, index) => {
      expect(sheet[index]).toBeCloseTo(value);
    });
  });

  it("cuts the whole image when the paper fills it", async () => {
    const { prepareEdition } = await loadModule();

    await prepareEdition("https://cdn/a.png", { fold: null, paper: null });

    expect(cutsBySrc.get("https://cdn/a.png")?.[0]).toEqual([0, 0, 1000, 1500]);
  });

  it("prepares an edition once for every viewport wider than the letter", async () => {
    const { prepareEdition } = await loadModule();

    await prepareEdition("https://cdn/a.png", LAYOUT);
    window.innerWidth = 1600;
    await prepareEdition("https://cdn/a.png", LAYOUT);

    expect(decoded).toEqual(["https://cdn/a.png"]);
  });

  it("keeps a held edition's bitmaps open however many others are prepared", async () => {
    const { holdEdition, prepareEdition } = await loadModule();
    const held = holdEdition("https://cdn/held.png", LAYOUT);
    await held.edition;

    for (let i = 0; i < 8; i += 1)
      await prepareEdition(`https://cdn/${i}.png`, LAYOUT);
    await Promise.resolve();
    expect(closedCount("https://cdn/held.png")).toBe(0);

    held.release();
    for (let i = 8; i < 16; i += 1)
      await prepareEdition(`https://cdn/${i}.png`, LAYOUT);
    await Promise.resolve();
    expect(closedCount("https://cdn/held.png")).toBeGreaterThan(0);
  });
});
