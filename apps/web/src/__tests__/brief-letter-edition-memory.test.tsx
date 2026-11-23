// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/briefing/utils/frontPaper", () => ({
  frontPaper: () => [240, 236, 228],
}));

import { BriefLetter } from "@/features/briefing/components/BriefLetter";
import type { FoldedBriefSummary } from "@/features/briefing/utils/briefCard";

const LETTER_COUNT = 50;
/** Letters inside the viewport's neighbourhood at once as the chat scrolls. */
const NEAR_AT_ONCE = 3;
/** Four editions of a sheet and three panels each. */
const OPEN_BITMAPS_MAX = 4 * 4;

interface FakeBitmap {
  width: number;
  height: number;
  isClosed: boolean;
  close: () => void;
}

const bitmaps: FakeBitmap[] = [];
const drawnClosed: FakeBitmap[] = [];

class FakeImage {
  crossOrigin = "";
  src = "";
  naturalWidth = 1000;
  naturalHeight = 1500;
  decode() {
    return Promise.resolve();
  }
}

function fakeCreateImageBitmap(
  _source: FakeImage,
  _x: number,
  _y: number,
  _w: number,
  _h: number,
  options: { resizeWidth: number; resizeHeight: number },
): Promise<FakeBitmap> {
  const bitmap: FakeBitmap = {
    width: options.resizeWidth,
    height: options.resizeHeight,
    isClosed: false,
    close() {
      bitmap.isClosed = true;
      bitmap.width = 0;
      bitmap.height = 0;
    },
  };
  bitmaps.push(bitmap);
  return Promise.resolve(bitmap);
}

/** Observers watching each element, so a test can move it in and out of the viewport. */
const watchers = new Map<Element, Set<FakeIntersectionObserver>>();

class FakeIntersectionObserver {
  private readonly watched = new Set<Element>();
  constructor(
    private readonly callback: (entries: IntersectionObserverEntry[]) => void,
  ) {}
  observe(element: Element) {
    this.watched.add(element);
    watchers.set(element, (watchers.get(element) ?? new Set()).add(this));
  }
  unobserve(element: Element) {
    this.watched.delete(element);
    watchers.get(element)?.delete(this);
  }
  disconnect() {
    for (const element of this.watched) watchers.get(element)?.delete(this);
    this.watched.clear();
  }
  report(target: Element, isIntersecting: boolean) {
    this.callback([{ target, isIntersecting } as IntersectionObserverEntry]);
  }
}

async function setNear(letter: Element, isNear: boolean) {
  await act(async () => {
    for (const observer of watchers.get(letter) ?? [])
      observer.report(letter, isNear);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function brief(index: number): FoldedBriefSummary {
  return {
    headline: `Brief ${index}`,
    date: "2026-10-22",
    kind: "daily",
    imageUrl: `https://cdn/edition-${index}.png`,
    editionFold: 0.3,
    editionPaper: [0, 0, 1, 1],
    editionName: null,
    stampCityName: null,
    needsYouCount: 0,
  };
}

const trigger = {
  open: () => undefined,
  warm: () => undefined,
  isBusy: false,
  isLifted: false,
};

/** A chat of letters, one root element each, in order. */
function renderLetters(count: number): Element[] {
  const briefs = Array.from({ length: count }, (_, index) => brief(index));
  const { container } = render(
    <div>
      {briefs.map((letter) => (
        <BriefLetter key={letter.headline} brief={letter} trigger={trigger} />
      ))}
    </div>,
  );
  return [...(container.firstElementChild?.children ?? [])];
}

function openBitmaps(): number {
  return bitmaps.filter((bitmap) => !bitmap.isClosed).length;
}

describe("a chat of many briefing letters", () => {
  beforeEach(() => {
    bitmaps.length = 0;
    drawnClosed.length = 0;
    watchers.clear();
    vi.stubGlobal("Image", FakeImage);
    vi.stubGlobal("createImageBitmap", fakeCreateImageBitmap);
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: (bitmap: FakeBitmap) => {
        if (bitmap.isClosed) drawnClosed.push(bitmap);
      },
    } as unknown as CanvasRenderingContext2D);
    window.innerWidth = 1280;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps a few editions open however far it is scrolled, and every letter keeps its face", async () => {
    const letters = renderLetters(LETTER_COUNT);
    let mostOpen = 0;

    for (const [index, letter] of letters.entries()) {
      await setNear(letter, true);
      if (index >= NEAR_AT_ONCE)
        await setNear(letters[index - NEAR_AT_ONCE], false);
      mostOpen = Math.max(mostOpen, openBitmaps());
    }

    expect(bitmaps.length).toBeGreaterThanOrEqual(LETTER_COUNT * 4);
    expect(mostOpen).toBeLessThanOrEqual(OPEN_BITMAPS_MAX);
    expect(openBitmaps()).toBeLessThanOrEqual(OPEN_BITMAPS_MAX);
    for (const letter of letters)
      expect(letter.querySelector("canvas")).not.toBeNull();
    expect(drawnClosed).toEqual([]);
  });

  it("readies a letter again when it comes back, without redrawing a closed face", async () => {
    const letters = renderLetters(8);
    for (const letter of letters) {
      await setNear(letter, true);
      await setNear(letter, false);
    }
    const preparedBefore = bitmaps.length;

    await setNear(letters[0], true);

    expect(bitmaps.length).toBe(preparedBefore + 4);
    expect(letters[0].querySelector("canvas")).not.toBeNull();
    expect(drawnClosed).toEqual([]);
  });
});
