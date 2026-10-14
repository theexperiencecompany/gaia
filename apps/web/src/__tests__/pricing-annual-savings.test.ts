/**
 * The annual discount is one number, and it has to be the one the prices
 * actually describe. A hardcoded "Save 25%" next to a $30/mo vs $300/yr
 * lineup was overstating the discount by half — the same card's derived
 * "2 months free" badge already said 16.7%.
 */

import { describe, expect, it } from "vitest";

import { MONTHS_PER_YEAR } from "@/features/pricing/constants";
import {
  getAnnualSavingsPercent,
  monthsFreeFromPrices,
} from "@/features/pricing/utils/annualSavings";

// The live GAIA Pro lineup, in cents: $30/month, $300/year.
const MONTHLY_CENTS = 3_000;
const YEARLY_CENTS = 30_000;

describe("getAnnualSavingsPercent", () => {
  it("reports the real discount for the live $30/mo vs $300/yr lineup", () => {
    // $360 billed monthly vs $300 billed yearly = 16.67% off.
    expect(
      getAnnualSavingsPercent(MONTHLY_CENTS * MONTHS_PER_YEAR, YEARLY_CENTS),
    ).toBe(17);
  });

  it("reports no saving when there is nothing to compare", () => {
    expect(getAnnualSavingsPercent(0, YEARLY_CENTS)).toBe(0);
    expect(getAnnualSavingsPercent(MONTHLY_CENTS * MONTHS_PER_YEAR, 0)).toBe(0);
  });
});

/** Twelve monthly payments against a yearly price, both in cents. */
const monthsFree = (yearlyCents: number) =>
  monthsFreeFromPrices(MONTHLY_CENTS * MONTHS_PER_YEAR, yearlyCents);

describe("monthsFreeFromPrices", () => {
  it("counts the live $300/yr lineup as two months free", () => {
    expect(monthsFree(YEARLY_CENTS)).toBe(2);
  });

  it("never rounds a part month up into a free one", () => {
    // $270/yr with 40% off is $162: $198 saved, 6.6 months of $30.
    expect(monthsFree(16_200)).toBe(6);
    // $1 short of a whole third month free.
    expect(monthsFree(27_100)).toBe(2);
  });

  it("counts a saving of exactly N months as N", () => {
    expect(monthsFree(27_000)).toBe(3);
    // 58.33% off: a rounded percentage would read 6.96 and floor to 6.
    expect(monthsFree(15_000)).toBe(7);
    expect(monthsFree(18_000)).toBe(6);
  });

  it("reports no months when there is nothing to compare or nothing saved", () => {
    expect(monthsFree(MONTHLY_CENTS * MONTHS_PER_YEAR)).toBe(0);
    expect(monthsFree(0)).toBe(0);
    expect(monthsFreeFromPrices(0, YEARLY_CENTS)).toBe(0);
  });
});
