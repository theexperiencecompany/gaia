"use client";

import { useRouter } from "next/navigation";
import { RaisedButton } from "@/components/ui/raised-button";

import type { Plan } from "../api/pricingApi";
import { ENTERPRISE_CTA_COPY, ENTERPRISE_PRICE_SUB_LINE } from "../constants";
import { PricingCardFeatures } from "./PricingCardFeatures";
import { PricingCardHeader } from "./PricingCardHeader";
import { PRICE_HEADLINE_ROW_CLASS } from "./PricingCardPrice";

interface EnterpriseCardProps {
  plan: Plan;
  ctaHref: string;
}

/**
 * Enterprise as a full card beside Pro — same shell, header and feature list
 * as `PricingCard`, with a contact CTA where the price and checkout would be:
 * Enterprise is quoted, not sold self-serve.
 */
export function EnterpriseCard({ plan, ctaHref }: EnterpriseCardProps) {
  const router = useRouter();

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-3xl bg-zinc-800/50 backdrop-blur-lg">
      <PricingCardHeader
        title={plan.name}
        description={plan.description}
        isCurrentPlan={false}
      />

      {/* Same boxes as PricingCardPrice / PricingCardCta, line for line, so the
          price, the button and the feature list sit level with Pro's. */}
      <div className="px-6 pb-5">
        <div className={PRICE_HEADLINE_ROW_CLASS}>
          <span className="text-5xl font-semibold tracking-tight">Custom</span>
        </div>
        <div className="mt-1.5 flex min-h-6 items-center gap-2">
          <span className="text-sm font-normal text-zinc-400">
            {ENTERPRISE_PRICE_SUB_LINE}
          </span>
        </div>
      </div>

      <div className="px-6 pb-4">
        <RaisedButton
          className="w-full text-black!"
          color="#00bbff"
          onClick={() => router.push(ctaHref)}
        >
          {ENTERPRISE_CTA_COPY}
        </RaisedButton>
      </div>

      <PricingCardFeatures
        features={plan.features}
        featuresHeading="Includes:"
        isPro={false}
      />
    </div>
  );
}
