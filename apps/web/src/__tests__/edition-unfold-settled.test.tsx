// @vitest-environment jsdom
/**
 * Once the letter has opened, its sliced fold panels give way to the one whole
 * sheet, so no seam is left where two panels meet; reduced motion fades the
 * whole sheet in without folding it.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const motionPreference = vi.hoisted(() => ({ reduced: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("motion/react")>()),
  useReducedMotion: () => motionPreference.reduced,
}));

import { EditionUnfold } from "@/features/briefing/components/EditionUnfold";
import type { PreparedEdition } from "@/features/briefing/utils/preparedEdition";

function bitmap(height: number): ImageBitmap {
  return { width: 540, height, close: () => undefined } as ImageBitmap;
}

const EDITION: PreparedEdition = {
  aspect: 2,
  width: 540,
  panels: [bitmap(360), bitmap(360), bitmap(360)],
  sheet: bitmap(1080),
  shares: [1 / 3, 1 / 3, 1 / 3],
  paper: "rgb(240, 236, 228)",
  isDarkPaper: false,
};

function recordDrawn(): ImageBitmap[] {
  const drawn: ImageBitmap[] = [];
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: (image: ImageBitmap) => drawn.push(image),
  } as unknown as CanvasRenderingContext2D);
  return drawn;
}

describe("settled edition", () => {
  afterEach(() => {
    motionPreference.reduced = false;
    vi.restoreAllMocks();
  });

  it("swaps the fold panels for the whole sheet once it has opened", async () => {
    const drawn = recordDrawn();

    render(<EditionUnfold edition={EDITION} alt="Your morning" />);
    const letter = screen.getByRole("img", { name: "Your morning" });
    expect(letter.querySelectorAll("canvas")).toHaveLength(3);

    await vi.waitFor(
      () => {
        expect(letter.querySelectorAll("canvas")).toHaveLength(1);
      },
      { timeout: 3000 },
    );
    expect(drawn.at(-1)).toBe(EDITION.sheet);
  });

  it("fades the whole sheet in under reduced motion, never folding it", () => {
    motionPreference.reduced = true;
    const drawn = recordDrawn();

    render(<EditionUnfold edition={EDITION} alt="Your morning" />);
    const letter = screen.getByRole("img", { name: "Your morning" });

    expect(letter.querySelectorAll("canvas")).toHaveLength(1);
    expect(drawn).toEqual([EDITION.sheet]);
  });
});
