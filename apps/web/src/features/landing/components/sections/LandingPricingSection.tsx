"use client";

import { ArrowRight02Icon } from "@icons";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { Link } from "@/i18n/navigation";

import LargeHeader from "../shared/LargeHeader";

export default function LandingPricingSection() {
  return (
    <section className="flex flex-col items-center px-4 py-24 sm:px-6 sm:py-32 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center gap-10">
        <LargeHeader headingText="Simple, transparent pricing" centered />
        <PricingCards durationIsMonth={false} />
        <Link
          href="https://docs.heygaia.io/self-hosting"
          className="flex items-center gap-1 text-sm text-zinc-400 transition-colors hover:text-zinc-200"
        >
          Self-host for free
          <ArrowRight02Icon width={14} height={14} />
        </Link>
      </div>
    </section>
  );
}
