"use client";

import { Skeleton } from "@heroui/skeleton";

import type { Plan } from "../api/pricingApi";
import { useProMonthlyPlan } from "../hooks/useProMonthlyPlan";
import { formatWholeOrCents } from "../utils/money";
import { getDailyPrice } from "../utils/priceDisplay";

interface ProDailyPriceHeadingProps {
  /** The words after the per-day price ("a day to never work again."). */
  afterPrice: string;
  /** The heading when the plans could not be read, so no price is guessed. */
  withoutPrice: string;
  initialPlans?: Plan[];
}

/** A heading led by the Pro monthly price per day ("$1"), from the live catalogue. */
export function ProDailyPriceHeading({
  afterPrice,
  withoutPrice,
  initialPlans,
}: ProDailyPriceHeadingProps) {
  const { plan, isLoading } = useProMonthlyPlan(initialPlans);
  if (plan)
    return `${formatWholeOrCents(getDailyPrice(plan.amount), plan.currency)} ${afterPrice}`;
  if (!isLoading) return withoutPrice;
  return (
    <>
      <Skeleton className="inline-block h-[0.8em] w-[1.4em] rounded-lg align-baseline" />{" "}
      {afterPrice}
    </>
  );
}
