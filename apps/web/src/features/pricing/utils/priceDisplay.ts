import { DAYS_PER_BILLING_MONTH, MONTHS_PER_YEAR } from "../constants";
import { getAnnualSavingsPercent, monthsFreeFromPrices } from "./annualSavings";

/** Every price figure a pricing card renders, in the plan currency's minor units. */
export interface PriceDisplay {
  /** A month's price; a yearly one is spread over twelve months, rounded to the minor unit. */
  perMonthMinor: number;
  /** The yearly charge; null on a monthly or free card. */
  yearlyTotalMinor: number | null;
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
): PriceDisplay {
  const isYearlyPaid = !durationIsMonth && price > 0;
  const perMonthMinor = isYearlyPaid
    ? Math.round(price / MONTHS_PER_YEAR)
    : price;
  const yearlyTotalMinor = isYearlyPaid ? price : null;
  // Savings vs paying monthly (originalPrice = 12× the monthly rate).
  const savePercent = originalPrice
    ? getAnnualSavingsPercent(originalPrice, price)
    : 0;
  let priceSubLine: string;
  if (price === 0) priceSubLine = "Free forever";
  else if (yearlyTotalMinor) priceSubLine = "Billed yearly";
  else priceSubLine = "Billed monthly";
  return {
    perMonthMinor,
    yearlyTotalMinor,
    priceSubLine,
    showSavings: !!yearlyTotalMinor && savePercent > 0,
    monthsFree: originalPrice ? monthsFreeFromPrices(originalPrice, price) : 0,
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
