"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

import { GrainOverlay } from "@/components/ui/GrainOverlay";
import { wallpapers } from "@/config/wallpapers";
import ComparisonGrid from "@/features/landing/components/sections/ComparisonGrid";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { ProDailyPriceHeading } from "@/features/pricing/components/ProDailyPriceHeading";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import type { Plan } from "../api/pricingApi";
import { FAQAccordion } from "./FAQAccordion";

const EMPTY_PLANS: Plan[] = [];

interface PricingPageProps {
  initialPlans?: Plan[];
}

export default function PricingPage({
  initialPlans = EMPTY_PLANS,
}: PricingPageProps) {
  const [isYearly, setIsYearly] = useState(false);

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_PAGE_VIEWED, {
      source: "landing_pricing",
    });
  }, []);

  return (
    <div className="relative flex min-h-screen w-full flex-col items-center justify-center pt-24 sm:pt-[30vh] lg:pt-[35vh]">
      <div className="absolute inset-0 top-0 z-0 h-[90vh] w-full">
        <Image
          src={wallpapers.pricing.png}
          alt="GAIA Pricing page Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-bottom opacity-80"
        />
        {/* Above the photo but below the fade, so the grain stops where the
            wallpaper does instead of speckling the solid background. Heavier
            than the shared default — this wallpaper is bright and soft-focus,
            so it swallows grain the darker blog artwork shows readily. */}
        <GrainOverlay className="opacity-[0.34]" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-linear-to-t from-background via-background to-transparent" />
      </div>

      <div className="relative z-1 flex w-full flex-col items-center gap-2 px-4 sm:px-6 lg:px-8">
        <div className="flex w-full flex-col items-center justify-center gap-3 text-white">
          <h1 className="font-serif text-3xl sm:text-5xl lg:text-7xl font-normal text-center">
            <ProDailyPriceHeading
              afterPrice="a day to never do busywork again."
              withoutPrice="Never do busywork again."
              initialPlans={initialPlans}
            />
          </h1>
          <span className="max-w-2xl text-center text-base sm:text-xl font-light text-zinc-100">
            The cheapest hire you'll ever make, whether you're running a company
            or just trying to get through your week.
          </span>
        </div>

        <div className="mt-5 mb-20 flex w-full flex-col items-center gap-6 font-medium">
          <BillingPeriodTabs
            isYearly={isYearly}
            onChange={setIsYearly}
            initialPlans={initialPlans}
          />

          <PricingCards
            durationIsMonth={!isYearly}
            initialPlans={initialPlans}
          />
        </div>

        <ComparisonGrid />

        <div className="relative mb-10 w-full max-w-7xl overflow-hidden rounded-4xl bg-zinc-900/50 px-8 backdrop-blur-sm">
          <FAQAccordion />
        </div>
      </div>

      <div className="w-full -mb-16 lg:-mb-20">
        <FinalSection />
      </div>
    </div>
  );
}
