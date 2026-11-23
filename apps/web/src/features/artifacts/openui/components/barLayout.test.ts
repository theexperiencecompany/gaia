import { describe, expect, it } from "vitest";
import { labelsFitUnderBars } from "./barLayout";

const SOURCES = ["Twitter", "Product Hunt", "newsletter", "organic"];
const WEEKS = Array.from({ length: 12 }, (_, i) => `W${i + 1}`);
// A 390px phone's figure, and an artifact page's figure at 1440.
const PHONE_PX = 358;
const PAGE_PX = 700;

describe("bar chart layout", () => {
  // Regression: at 390px the axis kept only "Product Hunt" and "organic" under four bars.
  it("lays four channel names sideways on a phone, where they cannot share the axis", () => {
    expect(labelsFitUnderBars(PHONE_PX, SOURCES)).toBe(false);
  });

  it("keeps them under vertical bars on a page wide enough for each", () => {
    expect(labelsFitUnderBars(PAGE_PX, SOURCES)).toBe(true);
  });

  it("keeps a dozen short week labels vertical on the page", () => {
    expect(labelsFitUnderBars(PAGE_PX, WEEKS)).toBe(true);
  });
});
