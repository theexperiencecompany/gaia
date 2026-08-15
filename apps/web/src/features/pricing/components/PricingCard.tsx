"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tick02Icon } from "@icons";
import NumberFlow from "@number-flow/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { TextMorph } from "torph/react";
import { RaisedButton } from "@/components/ui/raised-button";
import { ShineBorder } from "@/components/ui/shine-border";
import { useUser } from "@/features/auth/hooks/useUser";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import {
  type PricingOffer,
  usePricingModalStore,
} from "@/stores/pricingModalStore";

import { CENTS_PER_DOLLAR, MONTHS_PER_YEAR } from "../constants";
import { useDodoPayments } from "../hooks/useDodoPayments";
import { writePendingCheckout } from "../lib/pendingCheckout";

interface PricingCardProps {
  title: string;
  price: number;
  originalPrice?: number;
  description?: string;
  features?: string[];
  featuresHeading?: string;
  durationIsMonth: boolean;
  className?: string;
  planId?: string;
  isCurrentPlan?: boolean;
  hasActiveSubscription?: boolean;
  isPro?: boolean;
}

// Derives every price figure shown on a card from the raw cents + billing
// period, so the component body stays declarative.
function getPriceDisplay(
  price: number,
  originalPrice: number | undefined,
  durationIsMonth: boolean,
) {
  const isPaidTier = price > 0;
  const perMonthDollars =
    !durationIsMonth && isPaidTier
      ? Math.round(price / MONTHS_PER_YEAR / CENTS_PER_DOLLAR)
      : Math.round(price / CENTS_PER_DOLLAR);
  const yearlyTotalDollars =
    !durationIsMonth && isPaidTier
      ? Math.round(price / CENTS_PER_DOLLAR)
      : null;
  // Savings vs paying monthly (originalPrice = 12× the monthly rate).
  const savePercent =
    originalPrice && price ? Math.round((1 - price / originalPrice) * 100) : 0;
  let priceSubLine: string;
  if (price === 0) priceSubLine = "Free forever";
  else if (yearlyTotalDollars) priceSubLine = "Billed yearly";
  else priceSubLine = "Billed monthly";
  return {
    perMonthDollars,
    yearlyTotalDollars,
    priceSubLine,
    showSavings: !!yearlyTotalDollars && savePercent > 0,
    // ~16.7% off a year = pay for 10 months, get 12 → 2 months free.
    monthsFree: Math.round((savePercent / 100) * MONTHS_PER_YEAR),
  };
}

/** What the tier costs once the offer's percentage comes off. */
function getOfferPrice(price: number, offer: PricingOffer) {
  return Math.round(price * (1 - offer.discountPercent / 100));
}

export function PricingCard({
  title,
  price,
  originalPrice,
  description,
  features,
  featuresHeading,
  durationIsMonth,
  className,
  planId,
  isCurrentPlan,
  hasActiveSubscription,
  isPro = false,
}: PricingCardProps) {
  const {
    perMonthDollars,
    yearlyTotalDollars,
    priceSubLine,
    showSavings,
    monthsFree,
  } = getPriceDisplay(price, originalPrice, durationIsMonth);

  const {
    createSubscriptionAndRedirect,
    isLoading: isCreatingSubscription,
    error: paymentError,
  } = useDodoPayments();
  // An offer the modal was opened with (the founder's letter, for one) rides
  // along to checkout so the code is already applied when the page loads. The
  // discounted figures run through the same price maths as the list ones, so
  // the card can strike the list price and show what the reader will pay.
  const offer = usePricingModalStore((s) => s.offer);
  const offerDisplay =
    offer && price > 0
      ? getPriceDisplay(
          getOfferPrice(price, offer),
          originalPrice,
          durationIsMonth,
        )
      : null;
  const offerPerMonthDollars = offerDisplay?.perMonthDollars ?? null;
  const offerYearlyTotalDollars = offerDisplay?.yearlyTotalDollars ?? null;
  const offerMonthsFree = offerDisplay?.monthsFree ?? null;
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
      if (user.userId) router.push("/c");
      else router.push("/signup");
      return;
    }

    if (!user.userId) {
      // Carry the chosen plan across OAuth signup; useCheckoutResume picks it
      // up once authenticated and goes straight to the Dodo checkout.
      if (planId) writePendingCheckout(planId);
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

    await createSubscriptionAndRedirect(planId, offer?.discountCode);
  };

  const getButtonText = () => {
    if (isCreatingSubscription) return "Creating subscription...";
    if (isCurrentPlan && hasActiveSubscription) return "Current Plan";
    if (hasActiveSubscription && !isCurrentPlan) return "Switch Plan";
    return `Get GAIA ${title}`;
  };

  const isFree = price === 0;
  // A signed-in user with no active paid subscription is on the Free plan.
  const isOnFreePlan = !!user && !hasActiveSubscription;

  const renderCta = () => {
    if (!isFree) {
      return (
        <RaisedButton
          className="w-full text-black!"
          color="#00bbff"
          onClick={handleGetStarted}
          disabled={
            isCreatingSubscription || (isCurrentPlan && hasActiveSubscription)
          }
        >
          {getButtonText()}
        </RaisedButton>
      );
    }
    if (isOnFreePlan) {
      return (
        <Button isDisabled className="w-full" variant="flat">
          Current Plan
        </Button>
      );
    }
    return (
      <Button className="w-full" variant="flat" onPress={handleGetStarted}>
        Start for Free
      </Button>
    );
  };

  return (
    <div
      className={[
        "relative flex h-full w-full flex-col overflow-hidden rounded-3xl",
        "bg-zinc-800/50 backdrop-blur-lg",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {isPro && (
        <ShineBorder borderWidth={1} shineColor={["#00bbff", "#A7F3FF"]} />
      )}
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
          {offerPerMonthDollars !== null && (
            <span className="text-2xl font-normal text-zinc-500 line-through">
              ${perMonthDollars.toLocaleString()}
            </span>
          )}
          <NumberFlow
            value={offerPerMonthDollars ?? perMonthDollars}
            format={{
              style: "currency",
              currency: "USD",
              maximumFractionDigits: 0,
            }}
            willChange
            className={`text-5xl font-semibold tracking-tight${
              offerPerMonthDollars !== null ? " text-success" : ""
            }`}
          />
          <span className="text-base font-normal text-zinc-400">/ month</span>
        </div>
        {/* Sub-line \u2014 morphs on the billing toggle to keep card heights aligned */}
        <div className="mt-1.5 flex min-h-6 items-center gap-2">
          <TextMorph
            as="span"
            className="text-sm font-normal text-zinc-400"
            ease={{ stiffness: 200, damping: 20 }}
          >
            {priceSubLine}
          </TextMorph>
          {!!yearlyTotalDollars && (
            <>
              <span aria-hidden className="size-1 rounded-full bg-zinc-600" />
              {offerYearlyTotalDollars === null ? (
                <span className="text-sm font-normal text-zinc-400">
                  ${yearlyTotalDollars.toLocaleString()}
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-sm font-normal">
                  <span className="text-zinc-500 line-through">
                    ${yearlyTotalDollars.toLocaleString()}
                  </span>
                  <span className="text-success">
                    ${offerYearlyTotalDollars.toLocaleString()}
                  </span>
                </span>
              )}
            </>
          )}
          {showSavings && (
            <Chip color="success" size="sm" variant="flat">
              {offerMonthsFree === null ? (
                `${monthsFree} months free`
              ) : (
                <span className="flex items-center gap-1">
                  <span className="line-through opacity-60">{monthsFree}</span>
                  <span>{offerMonthsFree} months free</span>
                </span>
              )}
            </Chip>
          )}
        </div>
      </div>

      {/* CTA */}
      <div className="px-6 pb-5">
        {paymentError && (
          <div className="mb-3 rounded-xl bg-red-500/10 p-3">
            <p className="text-sm text-red-400">{paymentError}</p>
          </div>
        )}
        {renderCta()}
      </div>

      {/* Features — flex-1 so both cards fill remaining height equally */}
      <div className="flex flex-1 flex-col gap-2.5 px-6 py-5">
        {!!featuresHeading && (
          <span className="mb-1 text-sm font-medium text-zinc-500">
            {featuresHeading}
          </span>
        )}
        {!!features &&
          features.map((feature) => (
            <div
              key={feature}
              className="flex items-center gap-3 text-sm font-light"
            >
              <Tick02Icon
                height="15"
                width="15"
                className={`shrink-0 ${isPro ? "text-primary" : "text-zinc-500"}`}
              />
              <span className="whitespace-nowrap text-zinc-300">{feature}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
