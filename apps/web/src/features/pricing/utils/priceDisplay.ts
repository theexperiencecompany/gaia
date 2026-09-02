import type { PricingOffer } from "@/stores/pricingModalStore";

import { CENTS_PER_DOLLAR, MONTHS_PER_YEAR } from "../constants";
import { getAnnualSavingsPercent } from "./annualSavings";

/** Every price figure a pricing card renders, derived from raw cents. */
export interface PriceDisplay {
  perMonthDollars: number;
  yearlyTotalDollars: number | null;
  priceSubLine: string;
  showSavings: boolean;
  monthsFree: number;
}

// Derives every price figure shown on a card from the raw cents + billing
// period, so the component body stays declarative.
export function getPriceDisplay(
  price: number,
  originalPrice: number | undefined,
  durationIsMonth: boolean,
): PriceDisplay {
  const isPaidTier = price > 0;
  const perMonthDollars =
    !durationIsMonth && isPaidTier
      ? Math.round(price / MONTHS_PER_YEAR / CENTS_PER_DOLLAR)
      : Math.round(price / CENTS_PER_DOLLAR);
  const yearlyTotalDollars =
    !durationIsMonth && isPaidTier
      ? Math.round(price / CENTS_PER_DOLLAR)
      : null;
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
    // ~16.7% off a year = pay for 10 months, get 12 → 2 months free.
    monthsFree: Math.round((savePercent / 100) * MONTHS_PER_YEAR),
  };
}

/** What the tier costs once the offer's percentage comes off. */
export function getOfferPrice(price: number, offer: PricingOffer): number {
  return Math.round(price * (1 - offer.discountPercent / 100));
}
