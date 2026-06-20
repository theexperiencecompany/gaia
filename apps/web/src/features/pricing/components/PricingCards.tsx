"use client";

import { Skeleton } from "@heroui/skeleton";
import { useUser } from "@/features/auth/hooks/useUser";

import type { Plan } from "../api/pricingApi";
import { ANNUAL_PRICE_RETENTION } from "../constants";
import { usePricing } from "../hooks/usePricing";
import { convertToUSDCents } from "../utils/currencyConverter";
import { EnterpriseBar } from "./EnterpriseBar";
import { PricingCard } from "./PricingCard";

const ENTERPRISE_CONTACT_TEMPLATE = `Hey GAIA team,

We're looking at rolling GAIA out at work and wanted to reach out.

Company:
My role:
Team size this would cover:
What we'd want GAIA taking off our plates:
Tools our team lives in daily:
Deployment preference (cloud / private cloud / self host):
Compliance requirements (SOC 2, HIPAA, ISO, none):
Timeline to get live:
Anything else you should know:

Best way to reach me:

Happy to jump on a 20 minute call whenever works.`;

const ENTERPRISE_CONTACT_HREF =
  "/contact?type=support" +
  "&title=" +
  encodeURIComponent("Enterprise inquiry") +
  "&description=" +
  encodeURIComponent(ENTERPRISE_CONTACT_TEMPLATE);

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
  const user = useUser();

  // Only show loading if we're actually loading AND don't have any plans yet
  if (isLoading && (!plans || plans.length === 0)) {
    return (
      <div className="grid w-full max-w-2xl grid-cols-2 gap-4">
        <Skeleton className="h-96 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  // Only show error if we have an error AND no plans to display
  if (error && (!plans || plans.length === 0)) {
    return (
      <div className="grid w-full max-w-2xl grid-cols-2 gap-4">
        <div className="col-span-2 flex flex-col items-center justify-center rounded-2xl bg-red-500/10 p-6">
          <p className="text-center text-red-400">
            Unable to load pricing plans. Please refresh the page or try again
            later.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-red-500 px-4 py-2 text-white hover:bg-red-600"
          >
            Refresh Page
          </button>
        </div>
      </div>
    );
  }

  // If we have no plans at all, show a message
  if (!plans || plans.length === 0) {
    return (
      <div className="grid w-full max-w-2xl grid-cols-2 gap-3">
        <div className="col-span-2 flex flex-col items-center justify-center rounded-2xl bg-gray-500/10 p-8">
          <p className="text-center text-gray-400">
            No pricing plans available at the moment.
          </p>
        </div>
      </div>
    );
  }

  const isEnterprise = (plan: Plan) =>
    plan.name.toLowerCase().includes("enterprise");

  // Enterprise is shown as a full-width bar below the grid, not as a card.
  const enterprisePlan = plans.find(isEnterprise);

  // Priced tiers in the grid (Free + the paid plans for the chosen billing period).
  const cardPlans = plans.filter((plan: Plan) => {
    if (isEnterprise(plan)) return false;
    if (plan.amount === 0) return true;
    if (durationIsMonth) return plan.duration === "monthly";
    return plan.duration === "yearly";
  });

  // Sort: Free first, then paid plans by amount.
  const sortedPlans = cardPlans.toSorted((a: Plan, b: Plan) => {
    if (a.amount === 0) return -1;
    if (b.amount === 0) return 1;
    return a.amount - b.amount;
  });

  // Size the whole block (cards + Enterprise bar) so each tier keeps the width
  // it would have in a 3-column layout: a 2-tier lineup uses a 2-column grid in
  // a ~2xl block, a 3-tier lineup the full 5xl. The Enterprise bar is w-full, so
  // it always spans the exact width of the cards above it.
  const tierCount = sortedPlans.length;
  const blockWidthClass =
    tierCount >= 3 ? "max-w-5xl" : tierCount === 2 ? "max-w-2xl" : "max-w-sm";
  const gridColsClass =
    tierCount >= 3
      ? "sm:grid-cols-3"
      : tierCount === 2
        ? "sm:grid-cols-2"
        : "sm:grid-cols-1";

  return (
    <div className={`mx-auto flex w-full flex-col gap-3 ${blockWidthClass}`}>
      <div className={`grid grid-cols-1 items-stretch gap-3 ${gridColsClass}`}>
        {sortedPlans.map((plan: Plan, index: number) => {
          const isPro = plan.name.toLowerCase().includes("pro");
          // Free leads its list with "Includes:"; each paid tier builds on the
          // one before it ("Everything in Free, plus").
          const featuresHeading =
            index === 0
              ? "Includes:"
              : `Everything in ${sortedPlans[index - 1].name}, plus`;
          // Convert any currency to USD cents for display
          const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);

          // Every paid annual plan carries the same discount, so the pre-discount
          // price (what 12 monthly payments would cost) is the annual price
          // divided by the retained fraction.
          const originalPriceInUSDCents =
            !durationIsMonth && plan.amount > 0
              ? Math.round(priceInUSDCents / ANNUAL_PRICE_RETENTION)
              : undefined;

          // Determine if this is the user's current plan (only when authenticated)
          const isCurrentPlan =
            user && subscriptionStatus?.current_plan
              ? subscriptionStatus.current_plan.id === plan.id
              : false;

          // Only consider truly active subscriptions when user is logged in
          const hasActiveSubscription = user
            ? subscriptionStatus?.is_subscribed &&
              subscriptionStatus?.subscription?.status === "active"
            : false;

          return (
            <PricingCard
              // Key by tier name (not plan.id) so the same card instance persists
              // across the monthly/yearly toggle — letting NumberFlow animate the
              // price change instead of remounting a fresh component.
              key={plan.name}
              planId={plan.dodo_product_id} // Use dodo_product_id instead of id
              durationIsMonth={durationIsMonth}
              features={plan.features}
              featuresHeading={featuresHeading}
              description={plan.description} // Pass the description from backend
              price={priceInUSDCents} // Always in USD cents
              originalPrice={originalPriceInUSDCents}
              title={plan.name}
              isCurrentPlan={isCurrentPlan}
              hasActiveSubscription={hasActiveSubscription}
              isPro={isPro}
            />
          );
        })}
      </div>

      {enterprisePlan && (
        <EnterpriseBar
          plan={enterprisePlan}
          ctaHref={ENTERPRISE_CONTACT_HREF}
        />
      )}
    </div>
  );
}
