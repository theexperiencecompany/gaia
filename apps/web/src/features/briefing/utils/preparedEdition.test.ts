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
  _x: number,
  _y: number,
  _w: number,
  _h: number,
  options: { resizeWidth: number; resizeHeight: number },
): Promise<FakeBitmap> {
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
