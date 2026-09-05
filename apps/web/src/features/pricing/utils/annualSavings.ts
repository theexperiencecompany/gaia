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
