"use client";

import { useEffect } from "react";
import { ShineBorder } from "@/components/ui/shine-border";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import type { CheckoutSource } from "../api/pricingApi";
import { usePricingCardPrice } from "../hooks/usePricingCardPrice";
import type { PlanViewerState } from "../types";
import { PricingCardCta } from "./PricingCardCta";
import { PricingCardFeatures } from "./PricingCardFeatures";
import { PricingCardHeader } from "./PricingCardHeader";
import { PricingCardPrice } from "./PricingCardPrice";

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
  isPro?: boolean;
  /** The viewer's relationship to this plan — computed once by PricingCards
   * (see `getPlanViewerState`). While "unknown" the CTA is held disabled
   * instead of risking a paying user triggering a duplicate checkout via a
   * stale "not subscribed" read. Always "available" for a logged-out
   * visitor. Defaults to "available" so a standalone render (e.g. a demo
   * card with no plan context) shows an actionable CTA. */
  planViewerState?: PlanViewerState;
  checkoutSource?: CheckoutSource;
  /** The onboarding wizard introduces the plan in GAIA's own bubbles, so the
   * card there carries no name or tagline of its own. */
  hideHeader?: boolean;
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
  isPro = false,
  planViewerState = "available",
  checkoutSource,
  hideHeader = false,
}: PricingCardProps) {
  const { list, offer } = usePricingCardPrice({
    price,
    originalPrice,
    durationIsMonth,
  });

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_PLAN_VIEWED, {
      plan_title: title,
      plan_id: planId,
      price,
      is_monthly: durationIsMonth,
      // Same cards render on the pricing page and inside the onboarding
      // payment stage; without this the two funnels are one number.
      source: checkoutSource,
    });
  }, [title, planId, price, durationIsMonth, checkoutSource]);

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
      {hideHeader ? (
        <div className="pt-6" />
      ) : (
        <PricingCardHeader
          title={title}
          description={description}
          isCurrentPlan={planViewerState === "current"}
        />
      )}
      <PricingCardPrice list={list} offer={offer} />
      <PricingCardCta
        title={title}
        price={price}
        durationIsMonth={durationIsMonth}
        planId={planId}
        planViewerState={planViewerState}
        checkoutSource={checkoutSource}
      />
      <PricingCardFeatures
        features={features}
        featuresHeading={featuresHeading}
        isPro={isPro}
      />
    </div>
  );
}
