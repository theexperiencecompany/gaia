"use client";

import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import Image from "next/image";
import { useEffect, useState } from "react";

import { wallpapers } from "@/config/wallpapers";
import ComparisonGrid from "@/features/landing/components/sections/ComparisonGrid";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import type { Plan } from "../api/pricingApi";
import { FAQAccordion } from "./FAQAccordion";

interface PricingPageProps {
  initialPlans?: Plan[];
}

export default function PricingPage({ initialPlans = [] }: PricingPageProps) {
  const [isYearly, setIsYearly] = useState(false);

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.SUBSCRIPTION_PAGE_VIEWED, {
      source: "landing_pricing",
    });
  }, []);

  return (
    <div className="flex min-h-screen w-screen flex-col items-center justify-center pt-[35vh]">
      <div className="fixed inset-0 top-0 z-0 h-[90vh] w-full">
        <Image
          src={wallpapers.pricing.png}
          alt="GAIA Pricing page Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-bottom opacity-80"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-linear-to-t from-background via-background to-transparent" />
      </div>

      <div className="relative z-1 flex flex-col items-center gap-2">
        <div className="flex w-full flex-col items-center justify-center gap-3 text-white">
          <h1 className="font-serif text-7xl font-normal">
            $1 a day to never do busywork again.
          </h1>
          <span className="max-w-2xl text-center text-xl font-light text-zinc-100">
            The cheapest hire you'll ever make, whether you're running a company
            or just trying to get through your week.
          </span>
        </div>

        <div className="mt-5 mb-20 flex w-full flex-col items-center gap-6 font-medium">
          <Switch
            isSelected={isYearly}
            onValueChange={setIsYearly}
            color="primary"
          >
            <div className="flex items-center gap-2 text-white">
              Annually
              <Chip color={"primary"} size="sm">
                <div className="text-sm font-medium">Save 25%</div>
              </Chip>
            </div>
          </Switch>

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
