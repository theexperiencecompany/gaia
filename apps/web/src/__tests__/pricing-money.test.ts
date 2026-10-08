/**
 * An API amount is minor units in its own currency. Dividing every amount by
 * 100 shows ¥1000 as ¥10 and 1.500 KWD as 15.00; the exponent is the currency's.
 */
import { describe, expect, it } from "vitest";

import {
  currencyExponent,
  formatMoney,
  formatWholeOrCentsUSD,
  toMajorUnits,
} from "@/features/pricing/utils/money";
import { getPriceDisplay } from "@/features/pricing/utils/priceDisplay";

describe("money", () => {
  it("divides by the currency's own exponent", () => {
    expect(currencyExponent("USD")).toBe(2);
    expect(currencyExponent("JPY")).toBe(0);
    expect(currencyExponent("KWD")).toBe(3);
    expect(toMajorUnits(1000, "JPY")).toBe(1000);
    expect(toMajorUnits(1500, "KWD")).toBe(1.5);
  });

  it("formats with the charged currency's symbol", () => {
    expect(formatMoney(2584, "EUR")).toBe("€25.84");
    expect(formatMoney(1000, "JPY")).toBe("¥1,000");
  });

  it("a whole-dollar price drops its cents, and zero reads Free", () => {
    expect(formatWholeOrCentsUSD(3000)).toBe("$30");
    expect(formatWholeOrCentsUSD(3050)).toBe("$30.50");
    expect(formatWholeOrCentsUSD(0)).toBe("Free");
  });

  it("a pricing card prices a zero-exponent currency in whole units", () => {
    expect(getPriceDisplay(1000, undefined, true, "JPY").perMonthDollars).toBe(
      1000,
    );
  });
});
