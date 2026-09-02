"use client";

import { ArrowRight02Icon } from "@icons";
import Link from "next/link";
import { useState } from "react";

import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import LargeHeader from "../shared/LargeHeader";

export default function PricingSection() {
  const [isYearly, setIsYearly] = useState(false);

  return (
    <section className="flex w-full flex-col items-center px-4 py-16 sm:px-6 sm:py-24">
      <LargeHeader
        chipText="Pricing"
        headingText="$1 a day to never work again."
        subHeadingText="The cheapest hire you'll ever make."
        centered
      />

      <div className="mt-8 flex w-full flex-col items-center gap-6">
        <BillingPeriodTabs isYearly={isYearly} onChange={setIsYearly} />

        <PricingCards durationIsMonth={!isYearly} />

        <Link
          href="/pricing"
          className="flex items-center gap-1 text-sm text-zinc-400 transition hover:text-zinc-200"
        >
          Compare plans in detail
          <ArrowRight02Icon width={16} height={16} />
        </Link>
      </div>
    </section>
  );
}
