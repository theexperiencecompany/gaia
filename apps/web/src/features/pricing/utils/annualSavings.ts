import type { Plan } from "../api/pricingApi";
import { MONTHS_PER_YEAR } from "../constants";

/**
 * The annual discount, derived from the two prices that actually exist rather
 * than written into copy. A hardcoded percentage drifts the moment either
 * price moves, and drifted: "Save 25%" sat next to a $30/mo vs $300/yr lineup
 * that saves 17%.
 */
export function getAnnualSavingsPercent(
  fullPriceCents: number,
  discountedPriceCents: number,
): number {
  if (fullPriceCents <= 0 || discountedPriceCents <= 0) return 0;
  return Math.round((1 - discountedPriceCents / fullPriceCents) * 100);
}

/**
 * The whole months of the monthly rate a yearly price gives back, from the
 * prices rather than a rounded percentage. Floored: a savings claim may
 * understate a part month, never round one up into a free one.
 */
export function monthsFreeFromPrices(
  fullPriceCents: number,
  discountedPriceCents: number,
): number {
  if (fullPriceCents <= 0 || discountedPriceCents <= 0) return 0;
  const savedCents = Math.max(0, fullPriceCents - discountedPriceCents);
  return Math.floor((savedCents * MONTHS_PER_YEAR) / fullPriceCents);
}

/**
 * Whether `candidate` is the monthly row a yearly plan's saving is measured
 * against: same tier, billed monthly, and in the same currency. Rows in two
 * currencies cannot be compared without an exchange rate, so they never are;
 * the card then claims no saving, and the mismatch is reported.
 */
export function isMonthlyTwin(candidate: Plan, yearly: Plan): boolean {
  if (candidate.plan_type !== yearly.plan_type) return false;
  if (candidate.duration !== "monthly") return false;
  if (candidate.currency === yearly.currency) return true;
  console.error(
    `Pricing: the ${yearly.plan_type} monthly row is in ${candidate.currency} but the yearly row is in ${yearly.currency}; no saving is shown`,
  );
  return false;
}
