import { DAYS_PER_BILLING_MONTH, MONTHS_PER_YEAR } from "../constants";
import {
  getAnnualSavingsPercent,
  monthsFreeFromSavings,
} from "./annualSavings";
import { toMajorUnits } from "./money";

/** Every price figure a pricing card renders, derived from minor units. */
export interface PriceDisplay {
  perMonthDollars: number;
  yearlyTotalDollars: number | null;
  priceSubLine: string;
  showSavings: boolean;
  monthsFree: number;
}

// Derives every price figure shown on a card from the minor units + billing
// period, so the component body stays declarative.
export function getPriceDisplay(
  price: number,
  originalPrice: number | undefined,
  durationIsMonth: boolean,
  currency: string,
): PriceDisplay {
  const isPaidTier = price > 0;
  const priceMajor = toMajorUnits(price, currency);
  const perMonthDollars =
    !durationIsMonth && isPaidTier
      ? Math.round(priceMajor / MONTHS_PER_YEAR)
      : Math.round(priceMajor);
  const yearlyTotalDollars =
    !durationIsMonth && isPaidTier ? Math.round(priceMajor) : null;
  // Savings vs paying monthly (originalPrice = 12× the monthly rate).
  const savePercent = originalPrice
    ? getAnnualSavingsPercent(originalPrice, price)
    : 0;
  let priceSubLine: string;
  if (price === 0) priceSubLine = "Free forever";
  else if (yearlyTotalDollars) priceSubLine = "Billed yearly";
  else priceSubLine = "Billed monthly";
  return {
    perMonthDollars,
    yearlyTotalDollars,
    priceSubLine,
    showSavings: !!yearlyTotalDollars && savePercent > 0,
    monthsFree: monthsFreeFromSavings(savePercent),
  };
}

/** What the tier costs once the offer's percentage comes off. */
export function getOfferPrice(price: number, discountPercent: number): number {
  return Math.round(price * (1 - discountPercent / 100));
}

/** A monthly price spread over the days of a billing month, in minor units. */
export function getDailyPrice(monthlyPrice: number): number {
  return Math.round(monthlyPrice / DAYS_PER_BILLING_MONTH);
}
