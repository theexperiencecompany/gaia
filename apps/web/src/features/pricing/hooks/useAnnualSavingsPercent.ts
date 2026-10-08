"use client";

import { MONTHS_PER_YEAR } from "../constants";
import { getAnnualSavingsPercent, isMonthlyTwin } from "../utils/annualSavings";
import { isProPlan } from "../utils/planPredicates";
import { usePricing } from "./usePricing";

/**
 * What a yearly subscriber saves against twelve monthly payments, computed
 * from the live Pro rows. `null` until both rows are known — a savings badge
 * with no prices behind it is exactly how the wrong number shipped.
 */
export function useAnnualSavingsPercent(): number | null {
  const { plans } = usePricing();

  const yearly = plans.find(
    (plan) => isProPlan(plan) && plan.duration === "yearly",
  );
  const monthly = yearly
    ? plans.find((plan) => isMonthlyTwin(plan, yearly))
    : undefined;
  if (!monthly || !yearly) return null;

  const percent = getAnnualSavingsPercent(
    monthly.amount * MONTHS_PER_YEAR,
    yearly.amount,
  );
  return percent > 0 ? percent : null;
}
