/**
 * The annual discount is one number, and it has to be the one the prices
 * actually describe. A hardcoded "Save 25%" next to a $30/mo vs $300/yr
 * lineup was overstating the discount by half — the same card's derived
 * "2 months free" badge already said 16.7%.
 */

import { describe, expect, it } from "vitest";

import {
  ANNUAL_PRICE_RETENTION,
  MONTHS_PER_YEAR,
} from "@/features/pricing/constants";
import { getAnnualSavingsPercent } from "@/features/pricing/utils/annualSavings";

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

  it("agrees with the months-free badge derived from the same prices", () => {
    const percent = getAnnualSavingsPercent(
      MONTHLY_CENTS * MONTHS_PER_YEAR,
      YEARLY_CENTS,
    );
    expect(Math.round((percent / 100) * MONTHS_PER_YEAR)).toBe(2);
  });

  it("matches the annual retention constant the cards price against", () => {
    const fullYear = MONTHLY_CENTS * MONTHS_PER_YEAR;
    expect(
      getAnnualSavingsPercent(fullYear, fullYear * ANNUAL_PRICE_RETENTION),
    ).toBe(17);
  });

  it("reports no saving when there is nothing to compare", () => {
    expect(getAnnualSavingsPercent(0, YEARLY_CENTS)).toBe(0);
    expect(getAnnualSavingsPercent(MONTHLY_CENTS * MONTHS_PER_YEAR, 0)).toBe(0);
  });
});
