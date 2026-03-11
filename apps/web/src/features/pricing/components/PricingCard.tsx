"use client";

import { Chip } from "@heroui/chip";
import { Tick02Icon } from "@icons";
import { useRouter } from "next/navigation";
import type React from "react";
import { useEffect } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useUser } from "@/features/auth/hooks/useUser";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

import { useDodoPayments } from "../hooks/useDodoPayments";

interface Feature {
  text: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

interface PricingCardProps {
  title: string;
  price: number;
  originalPrice?: number;
  description?: string;
  featurestitle?: React.ReactNode;
  features?: (string | Feature)[];
  durationIsMonth: boolean;
  className?: string;
  planId?: string;
  isCurrentPlan?: boolean;
  hasActiveSubscription?: boolean;
  isPro?: boolean;
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
  isPro = false,
}: PricingCardProps) {
  const formatUSDPrice = (amountInCents: number) => {
    if (amountInCents === 0) return "$0";
    return `$${(amountInCents / 100).toFixed(0)}`;
  };

  const displayPrice = formatUSDPrice(price);
  const originalDisplayPrice = originalPrice
    ? formatUSDPrice(originalPrice)
    : null;

  // Yearly Pro: show per-month equivalent, note annual billing
  const monthlyEquivalent =
    !durationIsMonth && isPro && price > 0
      ? formatUSDPrice(Math.round(price / 12))
      : null;

  const {
    createSubscriptionAndRedirect,
    isLoading: isCreatingSubscription,
    error: paymentError,
  } = useDodoPayments();
  const user = useUser();
  const router = useRouter();

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_PLAN_VIEWED, {
      plan_title: title,
      plan_id: planId,
      price,
      is_monthly: durationIsMonth,
    });
  }, [title, planId, price, durationIsMonth]);

  const handleGetStarted = async () => {
    trackEvent(ANALYTICS_EVENTS.PRICING_PLAN_SELECTED, {
      plan_title: title,
      plan_id: planId,
      price,
      is_monthly: durationIsMonth,
      is_current_plan: isCurrentPlan,
      has_active_subscription: hasActiveSubscription,
      is_free_plan: price === 0,
    });

    if (price === 0) {
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

    await createSubscriptionAndRedirect(planId);
  };

  const getButtonText = () => {
    if (isCreatingSubscription) return "Creating subscription...";
    if (isCurrentPlan && hasActiveSubscription) return "Current Plan";
    if (hasActiveSubscription && !isCurrentPlan) return "Switch Plan";
    if (price === 0) return "Start for Free";
    return "Get GAIA Pro";
  };

  const isFree = price === 0;

  return (
    <div
      className={[
        "flex h-full w-full flex-col rounded-3xl",
        "bg-zinc-800/50 backdrop-blur-lg",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* Header: plan name + current plan badge */}
      <div className="flex flex-col gap-1.5 p-6 pb-4">
        {/* Reserve the same vertical space on both cards for the label row */}
        <div className="flex min-h-5 items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-semibold">{title}</span>
            {isCurrentPlan && hasActiveSubscription && (
              <Chip className="text-xs" color="success" variant="flat">
                Current Plan
              </Chip>
            )}
          </div>
          {isPro && !isCurrentPlan && (
            <Chip
              className="text-xs font-medium tracking-wide text-primary"
              variant="flat"
              color="primary"
            >
              Popular
            </Chip>
          )}
        </div>

        {/* Description — always reserve two lines to keep cards aligned */}
        <p className="line-clamp-2 min-h-10 text-sm font-light leading-relaxed text-zinc-400">
          {description ?? "\u00A0"}
        </p>
      </div>

      {/* Price */}
      <div className="px-6 pb-5">
        <div className="flex items-baseline gap-2">
          {originalDisplayPrice && !durationIsMonth && (
            <span className="text-2xl font-normal text-zinc-500 line-through">
              {originalDisplayPrice}
            </span>
          )}
          <span className="text-5xl font-semibold tracking-tight">
            {monthlyEquivalent ?? displayPrice}
          </span>
        </div>
        {/* Always render this line so height stays consistent */}
        <p className="mt-1 text-sm text-zinc-400 font-normal">
          {price > 0
            ? monthlyEquivalent
              ? `/ mo, billed ${displayPrice} / year`
              : "/ per month"
            : "\u00A0"}
        </p>
      </div>

      {/* CTA */}
      <div className="px-6 pb-5">
        {paymentError && (
          <div className="mb-3 rounded-xl bg-red-500/10 p-3">
            <p className="text-sm text-red-400">{paymentError}</p>
          </div>
        )}
        <RaisedButton
          className={`w-full ${isFree ? "text-zinc-400!" : "text-black!"}`}
          color={isFree ? "#2a2a2a" : "#00bbff"}
          onClick={handleGetStarted}
          disabled={
            isCreatingSubscription || (isCurrentPlan && hasActiveSubscription)
          }
        >
          {getButtonText()}
        </RaisedButton>
        <p className="mt-2 text-center text-xs text-zinc-500 font-light">
          {isFree
            ? "No credit card required"
            : "Cancel anytime · Secure payment"}
        </p>
      </div>

      {/* Features — flex-1 so both cards fill remaining height equally */}
      <div className="flex flex-1 flex-col gap-2.5 px-6 py-5">
        {featurestitle && (
          <p className="mb-0.5 text-xs uppercase text-zinc-500 font-normal">
            {featurestitle}
          </p>
        )}

        {!!features &&
          features.map((feature) => {
            const featureText =
              typeof feature === "string" ? feature : feature.text;
            const FeatureIcon =
              typeof feature === "object" && feature.icon
                ? feature.icon
                : Tick02Icon;

            return (
              <div
                key={featureText}
                className="flex items-start gap-3 text-sm font-light"
              >
                <FeatureIcon
                  height="15"
                  width="15"
                  className={`mt-0.5 shrink-0 ${isPro ? "text-primary" : "text-zinc-500"}`}
                />
                <span className="text-zinc-300">{featureText}</span>
              </div>
            );
          })}
      </div>
    </div>
  );
}
