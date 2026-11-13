"use client";

import type { Plan } from "../api/pricingApi";
import { MONTHS_PER_YEAR } from "../constants";
import {
  getAnnualSavingsPercent,
  isMonthlyTwin,
  monthsFreeFromPrices,
} from "../utils/annualSavings";
import { isProPlan } from "../utils/planPredicates";
import { getOfferPrice } from "../utils/priceDisplay";
import { usePricing } from "./usePricing";

interface AnnualSavingsOptions {
  /** Server-fetched plans, so the first render already has the figure. */
  initialPlans?: Plan[];
  /** An offer's percentage, taken off the yearly price before comparing. */
  offerPercent?: number;
}

/** A yearly saving against twelve monthly payments, as a percentage and as whole months. */
export interface AnnualSavings {
  percent: number;
  monthsFree: number;
}

/**
 * What a yearly subscriber saves against twelve monthly payments, computed
 * from the live Pro rows. `null` until both rows are known — a savings badge
 * with no prices behind it is exactly how the wrong number shipped.
 */
export function useAnnualSavings({
  initialPlans,
  offerPercent,
}: AnnualSavingsOptions = {}): AnnualSavings | null {
  const { plans } = usePricing(initialPlans);

  const yearly = plans.find(
    (plan) => isProPlan(plan) && plan.duration === "yearly",
  );
  const monthly = yearly
    ? plans.find((plan) => isMonthlyTwin(plan, yearly))
    : undefined;
  if (!monthly || !yearly) return null;

  const fullPrice = monthly.amount * MONTHS_PER_YEAR;
  const yearlyPrice = offerPercent
    ? getOfferPrice(yearly.amount, offerPercent)
    : yearly.amount;
  const percent = getAnnualSavingsPercent(fullPrice, yearlyPrice);
  if (percent <= 0) return null;
  return { percent, monthsFree: monthsFreeFromPrices(fullPrice, yearlyPrice) };
}
