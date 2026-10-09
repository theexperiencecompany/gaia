import type { Plan } from "../api/pricingApi";

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
