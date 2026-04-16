"use client";

import { Skeleton } from "@heroui/skeleton";
import {
  Brain02Icon,
  BuildingIcon,
  ConnectIcon,
  CustomerService01Icon,
  DiscordIcon,
  HeadsetIcon,
  LockIcon,
  StarsIcon,
} from "@icons";
import { useUser } from "@/features/auth/hooks/useUser";

import type { Plan } from "../api/pricingApi";
import { usePricing } from "../hooks/usePricing";
import { convertToUSDCents } from "../utils/currencyConverter";
import { PricingCard } from "./PricingCard";

// Enterprise icon pool — matched positionally to the feature list on the DB plan.
const ENTERPRISE_ICON_POOL = [BuildingIcon, LockIcon, ConnectIcon, HeadsetIcon];

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

  // Function to map features with icons
  const mapFeaturesWithIcons = (features: string[], isPro: boolean) => {
    return features.map((feature, index) => {
      // First feature: StarsIcon (representing rocket/launch)
      if (index === 0) {
        return { text: feature, icon: StarsIcon };
      }
      // Second feature: Brain02Icon
      if (index === 1) {
        return { text: feature, icon: Brain02Icon };
      }
      // Third feature: CustomerService01Icon (support/user)
      if (index === 2) {
        return { text: feature, icon: CustomerService01Icon };
      }
      // Fourth feature: DiscordIcon (only for Pro)
      if (index === 3 && isPro) {
        return { text: feature, icon: DiscordIcon };
      }
      // Default: return as string (will use Tick02Icon)
      return feature;
    });
  };

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
        <div className="col-span-2 flex flex-col items-center justify-center rounded-2xl border border-red-500/20 bg-red-500/10 p-8">
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

  // Filter plans by duration. Free and Enterprise always show regardless.
  const filteredPlans = plans.filter((plan: Plan) => {
    if (isEnterprise(plan)) return true;
    if (plan.amount === 0) return true;
    if (durationIsMonth) return plan.duration === "monthly";
    return plan.duration === "yearly";
  });

  // Sort: Free first, Enterprise last, paid plans in the middle by amount.
  const sortedPlans = filteredPlans.toSorted((a: Plan, b: Plan) => {
    if (isEnterprise(a)) return 1;
    if (isEnterprise(b)) return -1;
    if (a.amount === 0) return -1;
    if (b.amount === 0) return 1;
    return a.amount - b.amount;
  });

  let originalPriceInUSDCents: number;

  return (
    <div className="grid w-full max-w-5xl grid-cols-1 items-stretch gap-3 sm:grid-cols-3">
      {sortedPlans.map((plan: Plan) => {
        const isPro = plan.name.toLowerCase().includes("pro");
        const enterprise = isEnterprise(plan);
        // Convert any currency to USD cents for display
        const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);

        // Calculate original price for yearly plans (monthly * 12)
        if (!durationIsMonth && isPro) {
          // For yearly plans, assume 25% discount, so original = price / 0.75
          originalPriceInUSDCents = Math.round(priceInUSDCents / 0.75);
        }

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

        // Map features with icons
        const featuresWithIcons = enterprise
          ? plan.features.map((text, i) => ({
              text,
              icon: ENTERPRISE_ICON_POOL[i % ENTERPRISE_ICON_POOL.length],
            }))
          : mapFeaturesWithIcons(plan.features, isPro);

        return (
          <PricingCard
            key={plan.id}
            planId={plan.dodo_product_id} // Use dodo_product_id instead of id
            durationIsMonth={durationIsMonth}
            features={featuresWithIcons}
            featurestitle={
              enterprise
                ? "Everything from Pro, plus:"
                : isPro
                  ? "Everything in Free, plus:"
                  : undefined
            }
            description={plan.description} // Pass the description from backend
            price={priceInUSDCents} // Always in USD cents
            originalPrice={originalPriceInUSDCents}
            title={plan.name}
            isCurrentPlan={isCurrentPlan}
            hasActiveSubscription={hasActiveSubscription}
            isPro={isPro}
            isEnterprise={enterprise}
            priceLabel={enterprise ? "Custom" : undefined}
            ctaLabel={enterprise ? "Talk to the team" : undefined}
            ctaHref={enterprise ? ENTERPRISE_CONTACT_HREF : undefined}
          />
        );
      })}
    </div>
  );
}
