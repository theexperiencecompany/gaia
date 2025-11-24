"use client";

import { Chip } from "@heroui/chip";
import { useRouter } from "next/navigation";
import React from "react";
import { toast } from "sonner";

import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { Tick02Icon } from "@/icons";
import { posthog } from "@/lib";

// Removed currency import - using USD only
import { useDodoPayments } from "../hooks/useDodoPayments";

interface Feature {
  text: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

interface PricingCardProps {
  title: string;
  price: number; // Price in USD cents (already discounted if applicable)
  originalPrice?: number; // Original price before discount (for yearly plans)
  description?: string; // Add description prop for subtitle
  featurestitle?: React.ReactNode;
  features?: (string | Feature)[]; // Can be array of strings or Feature objects
  durationIsMonth: boolean;
  className?: string;
  planId?: string; // Add planId prop for backend integration
  isCurrentPlan?: boolean;
  hasActiveSubscription?: boolean;
}

export function PricingCard({
  title,
  price,
  originalPrice,
  description,
  featurestitle,
  features,
  durationIsMonth,
  className,
  planId,
  isCurrentPlan,
  hasActiveSubscription,
}: PricingCardProps) {

  // Always display in USD format - convert from smallest unit (cents)
  const formatUSDPrice = (amountInCents: number) => {
    if (amountInCents === 0) return { formatted: "$0", currency: "USD" };
    const dollars = amountInCents / 100;
    return {
      formatted: `$${dollars.toFixed(0)}`,
      currency: "USD",
    };
  };

  const finalPriceFormatted = formatUSDPrice(price);
  const originalPriceFormatted = originalPrice
    ? formatUSDPrice(originalPrice)
    : null;

  const {
    createSubscriptionAndRedirect,
    isLoading: isCreatingSubscription,
    error: paymentError,
  } = useDodoPayments();
  const user = useUser();
  const router = useRouter();

  const handleGetStarted = async () => {
    // Track pricing card interaction
    posthog.capture("pricing:plan_selected", {
      plan_title: title,
      plan_id: planId,
      price: price,
      is_monthly: durationIsMonth,
      is_current_plan: isCurrentPlan,
      has_active_subscription: hasActiveSubscription,
      is_free_plan: price === 0,
    });

    if (price === 0) {
      // Handle free plan - redirect to signup or dashboard
      if (user) router.push("/c");
      else router.push("/signup");
      return;
    }

    if (!user) {
      toast.error("Please sign in to subscribe to a plan");
      router.push("/login");
      return;
    }

    if (isCurrentPlan && hasActiveSubscription) {
      toast.info("This is your current active plan");
      return;
    }

    if (hasActiveSubscription && !isCurrentPlan) {
      toast.info(
        "Please cancel your current subscription before subscribing to a different plan",
      );
      return;
    }

    if (!planId) {
      toast.error("Plan not available. Please try again later.");
      return;
    }

    // Create subscription and redirect to Dodo payment page
    await createSubscriptionAndRedirect(planId);
  };

  // Determine button text based on plan type
  const getButtonText = () => {
    if (isCreatingSubscription) return "Creating subscription...";
    if (isCurrentPlan && hasActiveSubscription) return "Current Plan";
    if (hasActiveSubscription && !isCurrentPlan) return "Switch Plan";

    // New button text format
    if (price === 0) return "Go Free";
    return "Go Pro";
  };

  return (
    <div
      className={`relative w-full overflow-hidden rounded-3xl bg-white/10 backdrop-blur-sm ${className}`}
    >
      {/* Outer Card - Title Section (z-index: 1) */}
      <div className="relative z-[1] flex flex-col gap-2 border-none! p-6 pb-4">
        <div className="flex flex-row items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-semibold">{title}</span>
            {isCurrentPlan && hasActiveSubscription && (
              <Chip
                className="flex items-center gap-[2px] text-xs"
                color="success"
                variant="flat"
              >
                <span>Current Plan</span>
              </Chip>
            )}
          </div>
        </div>
      </div>

      {/* Inner Nested Card - Price & Button (z-index: -1) */}
      <div className="relative z-[-1] mx-4 mb-4 flex flex-col gap-4 overflow-hidden rounded-3xl bg-black/70 p-6 shadow-xl backdrop-blur-2xl">
        {/* Description/Subtitle */}
        {description && (
          <p className="font-sm text-sm leading-relaxed text-zinc-200">
            {description}
          </p>
        )}

        {/* Price Section */}
        <div className="relative z-[1] m-0! flex flex-col gap-0 border-none!">
          <div className="flex items-baseline gap-2 border-none!">
            {originalPriceFormatted && !durationIsMonth && (
              <span className="text-3xl font-normal text-red-500 line-through">
                {originalPriceFormatted.formatted}
              </span>
            )}
            <span className="text-5xl">{finalPriceFormatted.formatted}</span>
            {finalPriceFormatted.currency && (
              <span className="text-2xl">{finalPriceFormatted.currency}</span>
            )}
          </div>

          <span className="text-opacity-70 min-h-5 text-sm font-normal text-zinc-400">
            {price > 0 && (durationIsMonth ? "/ per month" : "/ per year")}
          </span>
        </div>

        {/* Button Section */}
        <div className="relative z-[1] space-y-3">
          {paymentError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="text-sm text-red-600">{paymentError}</p>
            </div>
          )}

          <RaisedButton
            className={`w-full ${price === 0 ? "text-zinc-400!" : "text-black!"} `}
            color={price === 0 ? "#3b3b3b" : "#00bbff"}
            onClick={handleGetStarted}
            disabled={
              isCreatingSubscription || (isCurrentPlan && hasActiveSubscription)
            }
          >
            {getButtonText()}
          </RaisedButton>
        </div>
      </div>

      {/* Features Section - Back in Outer Card */}
      <div className="relative z-[1] flex flex-1 flex-col gap-2 px-6 pb-6">
        {featurestitle}

        {!!features &&
          features.map((feature, index) => {
            // Handle both string and Feature object formats
            const featureText =
              typeof feature === "string" ? feature : feature.text;
            const FeatureIcon =
              typeof feature === "object" && feature.icon
                ? feature.icon
                : Tick02Icon;

            return (
              <div
                key={index}
                className="flex items-center gap-3 border-none! text-sm font-light"
              >
                <FeatureIcon
                  height="16"
                  width="16"
                  className="min-h-[20px] min-w-[22px] text-white"
                />
                {featureText}
              </div>
            );
          })}
      </div>
    </div>
  );
}
