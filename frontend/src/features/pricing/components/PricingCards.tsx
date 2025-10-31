"use client";

import { Skeleton } from "@heroui/skeleton";

import type { Plan } from "../api/pricingApi";
import { usePricing } from "../hooks/usePricing";
import { convertToUSDCents } from "../utils/currencyConverter";
import { PricingCard } from "./PricingCard";

interface PricingCardsProps {
  durationIsMonth?: boolean;
  initialPlans?: Plan[];
}

export function PricingCards({
  durationIsMonth = false,
  initialPlans = [],
}: PricingCardsProps) {
  const { plans, isLoading, error, subscriptionStatus } =
    usePricing(initialPlans);

  if (isLoading) {
    return (
      <div className="grid w-screen max-w-(--breakpoint-sm) grid-cols-2 gap-3">
        <Skeleton className="h-96 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !plans) {
    return (
      <div className="grid w-screen max-w-(--breakpoint-sm) grid-cols-2 gap-3">
        <div className="col-span-2 flex flex-col items-center justify-center rounded-2xl border border-red-500/20 bg-red-500/10 p-8">
          <p className="text-center text-red-400">
            Unable to load pricing plans. Please refresh the page or try again
            later.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-red-500 px-4 py-2 text-white hover:bg-red-600"
          >
            Refresh Page
          </button>
        </div>
      </div>
    );
  }

  // Filter plans by duration (always show free plan)
  const filteredPlans = plans.filter((plan: Plan) => {
    // Always show free plan regardless of selected duration
    if (plan.amount === 0) return true;

    // For paid plans, filter by duration
    if (durationIsMonth) return plan.duration === "monthly";
    return plan.duration === "yearly";
  });

  // Sort plans: Free first, then by amount
  const sortedPlans = filteredPlans.sort((a: Plan, b: Plan) => {
    if (a.amount === 0) return -1;
    if (b.amount === 0) return 1;
    return a.amount - b.amount;
  });

  return (
    <div className="grid w-screen max-w-(--breakpoint-sm) grid-cols-2 gap-3">
      {sortedPlans.map((plan: Plan) => {
        const isPro = plan.name.toLowerCase().includes("pro");
        // Convert any currency to USD cents for display
        const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);

        // Calculate original price for yearly plans (monthly * 12)
        let originalPriceInUSDCents;
        if (!durationIsMonth && isPro) {
          // For yearly plans, assume 25% discount, so original = price / 0.75
          originalPriceInUSDCents = Math.round(priceInUSDCents / 0.75);
        }

        const isCurrentPlan = subscriptionStatus?.current_plan?.id === plan.id;
        // Only consider truly active subscriptions (not just created ones)
        const hasActiveSubscription =
          subscriptionStatus?.is_subscribed &&
          subscriptionStatus?.subscription?.status === "active";

        return (
          <PricingCard
            key={plan.id}
            planId={plan.dodo_product_id} // Use dodo_product_id instead of id
            durationIsMonth={durationIsMonth}
            features={plan.features}
            // featurestitle={
            //   <div className="mb-1 flex flex-col border-none! text-sm font-light text-zinc-300">
            //     <span>What's Included?</span>
            //   </div>
            // }
            price={priceInUSDCents} // Always in USD cents
            originalPrice={originalPriceInUSDCents}
            title={plan.name}
            type={isPro ? "main" : "secondary"}
            isCurrentPlan={isCurrentPlan}
            hasActiveSubscription={hasActiveSubscription}
          />
        );
      })}
    </div>
  );
}
