import { describe, expect, it } from "vitest";

import {
  getContrastColor,
  getContrastRatio,
  getLuminance,
  parseColor,
} from "@/utils/colorUtils";

const WCAG_AA_NORMAL_TEXT = 4.5;

// Every custom background a RaisedButton is rendered with on the site.
const BUTTON_BACKGROUNDS = [
  "#00bbff",
  "#f5a524",
  "#0A84FF",
  "#037EE5",
  "#25D366",
  "#5865F2",
  "#611F69",
  "#3f3f46",
  "#2e2e2e",
  "#292929",
];

const luminanceOf = (hex: string): number => {
  const rgb = parseColor(hex);
  if (!rgb) throw new Error(`unparseable color ${hex}`);
  return getLuminance(rgb);
};

describe("getContrastColor", () => {
  it.each(BUTTON_BACKGROUNDS)(
    "picks a text color that meets WCAG AA on %s",
    (background) => {
      const luminance = luminanceOf(background);
      const text = getContrastColor(luminance);
      expect(
        getContrastRatio(luminance, luminanceOf(text)),
      ).toBeGreaterThanOrEqual(WCAG_AA_NORMAL_TEXT);
    },
  );

  it("picks black on the brand cyan", () => {
    expect(getContrastColor(luminanceOf("#00bbff"))).toBe("#000000");
  });

  it("picks white on a dark background", () => {
    expect(getContrastColor(luminanceOf("#292929"))).toBe("#ffffff");
  });
});
