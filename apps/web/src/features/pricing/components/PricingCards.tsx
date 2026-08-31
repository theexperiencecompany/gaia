"use client";

import { Skeleton } from "@heroui/skeleton";
import { useUser } from "@/features/auth/hooks/useUser";

import type { Plan } from "../api/pricingApi";
import { ANNUAL_PRICE_RETENTION } from "../constants";
import {
  useIsSubscriptionStatusUnknown,
  usePricing,
} from "../hooks/usePricing";
import { getPlanViewerState } from "../types";
import { convertToUSDCents } from "../utils/currencyConverter";
import { isProPlan } from "../utils/planPredicates";
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

// Enterprise is shown as a full-width bar below the grid, never as a priced card.
const isEnterprise = (plan: Plan) =>
  plan.name.toLowerCase().includes("enterprise");

interface PricingCardsProps {
  durationIsMonth?: boolean;
  initialPlans?: Plan[];
  /** Hide the Enterprise bar: the landing section and the upgrade modal both
   * sell the priced tiers, and Enterprise lives on the pricing page. */
  hideEnterprise?: boolean;
}

export function PricingCards({
  durationIsMonth = false,
  initialPlans = [],
  hideEnterprise = false,
}: PricingCardsProps) {
  const { plans, isLoading, error, subscriptionStatus } =
    usePricing(initialPlans);
  const user = useUser();
  // Whether the signed-in user's plan status is genuinely not yet known
  // (cold cache / user store still rehydrating). While true, `isCurrentPlan`
  // / `hasActiveSubscription` below are unresolvable — never infer "on free
  // plan" from that and let a paying user click into a duplicate checkout.
  const isSubscriptionStatusUnknown = useIsSubscriptionStatusUnknown();

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

  // Enterprise is shown as a full-width bar below the grid, not as a card.
  const enterprisePlan = hideEnterprise ? undefined : plans.find(isEnterprise);

  // Priced tiers in the grid for the chosen billing period. GAIA is paid-only,
  // so any $0 row is filtered out client-side as a safety net even if one
  // slips through from the backend.
  const cardPlans = plans.filter((plan: Plan) => {
    if (isEnterprise(plan)) return false;
    if (plan.amount === 0) return false;
    if (durationIsMonth) return plan.duration === "monthly";
    return plan.duration === "yearly";
  });

  // Sort paid plans by amount.
  const sortedPlans = cardPlans.toSorted(
    (a: Plan, b: Plan) => a.amount - b.amount,
  );

  // Size the whole block (cards + Enterprise bar) so each tier keeps the width
  // it would have in a 3-column layout: a 2-tier lineup uses a 2-column grid in
  // a ~2xl block, a 3-tier lineup the full 5xl. The Enterprise bar is w-full, so
  // it always spans the exact width of the cards above it.
  const tierCount = sortedPlans.length;
  let blockWidthClass = "max-w-sm";
  let gridColsClass = "sm:grid-cols-1";
  if (tierCount >= 3) {
    blockWidthClass = "max-w-5xl";
    gridColsClass = "sm:grid-cols-3";
  } else if (tierCount === 2) {
    blockWidthClass = "max-w-2xl";
    gridColsClass = "sm:grid-cols-2";
  }

  return (
    <div className={`mx-auto flex w-full flex-col gap-3 ${blockWidthClass}`}>
      <div className={`grid grid-cols-1 items-stretch gap-3 ${gridColsClass}`}>
        {sortedPlans.map((plan: Plan, index: number) => {
          const isPro = isProPlan(plan);
          // The first (cheapest) plan leads its list with "Includes:"; each
          // subsequent tier builds on the one before it ("Everything in X, plus").
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

          // The backend always sets plan_type ("free" | "pro") for an active
          // subscription, but current_plan can be null when the subscribed
          // product isn't in the active plan list — so don't rely on it. Pro is
          // the only paid tier, so the paid card is "current" if plan_type is
          // pro; fall back to a name match for any other (future) paid tier.
          const isCurrentPlan =
            user.userId && subscriptionStatus
              ? isPro
                ? subscriptionStatus.plan_type === "pro"
                : subscriptionStatus.current_plan?.name === plan.name
              : false;

          // Only consider truly active subscriptions when user is logged in
          const hasActiveSubscription = user
            ? !!(
                subscriptionStatus?.is_subscribed &&
                subscriptionStatus?.subscription?.status === "active"
              )
            : false;

          const planViewerState = getPlanViewerState({
            isSubscriptionStatusUnknown:
              !!user.userId && isSubscriptionStatusUnknown,
            isCurrentPlan: !!isCurrentPlan,
            hasActiveSubscription,
          });

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
              isPro={isPro}
              planViewerState={planViewerState}
            />
          );
        })}
      </div>

      {enterprisePlan && !hideEnterprise && (
        <EnterpriseBar
          plan={enterprisePlan}
          ctaHref={ENTERPRISE_CONTACT_HREF}
        />
      )}
    </div>
  );
}
