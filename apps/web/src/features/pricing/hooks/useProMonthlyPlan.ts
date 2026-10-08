"use client";

import type { Plan } from "../api/pricingApi";
import { isProPlan } from "../utils/planPredicates";
import { usePricing } from "./usePricing";

interface ProMonthlyPlan {
  /** The live Pro monthly row; undefined while loading or when the read failed. */
  plan: Plan | undefined;
  isLoading: boolean;
}

/** The Pro monthly row every "per month" and "per day" price is quoted from. */
export function useProMonthlyPlan(initialPlans?: Plan[]): ProMonthlyPlan {
  const { plans, plansLoading } = usePricing(initialPlans);
  return {
    plan: plans.find((p) => isProPlan(p) && p.duration === "monthly"),
    isLoading: plansLoading,
  };
}
