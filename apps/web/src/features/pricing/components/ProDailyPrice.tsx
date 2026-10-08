"use client";

import { Skeleton } from "@heroui/skeleton";

import type { Plan } from "../api/pricingApi";
import { useProMonthlyPlan } from "../hooks/useProMonthlyPlan";
import { formatWholeOrCents } from "../utils/money";
import { getDailyPrice } from "../utils/priceDisplay";

/** The Pro monthly price per day ("$1"), held as a skeleton until the plans arrive. */
export function ProDailyPrice({ initialPlans }: { initialPlans?: Plan[] }) {
  const { plan } = useProMonthlyPlan(initialPlans);
  if (!plan)
    return (
      <Skeleton className="inline-block h-[0.8em] w-[1.4em] rounded-lg align-baseline" />
    );
  return formatWholeOrCents(getDailyPrice(plan.amount), plan.currency);
}
