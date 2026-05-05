"use client";

import { ArrowRight01Icon } from "@icons";
import Link from "next/link";
import { PricingCards } from "@/features/pricing/components/PricingCards";

import LargeHeader from "../shared/LargeHeader";

export default function LandingPricingSection() {
  return (
    <div className="flex flex-col items-center justify-center gap-10 px-4 sm:px-6 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center justify-center rounded-2xl bg-gradient-to-b from-zinc-900 to-zinc-950 px-4 py-6 outline-1 outline-zinc-900 sm:rounded-3xl sm:p-8 lg:rounded-4xl lg:p-10">
        <LargeHeader headingText="Simple, transparent pricing" centered />
        <div className="mt-6 w-full sm:mt-8 lg:mt-10">
          <PricingCards durationIsMonth={false} />
        </div>
        <Link
          href="https://docs.heygaia.io/self-hosting"
          className="mt-4 flex items-center gap-1 text-sm text-zinc-400 transition-colors hover:text-zinc-200"
        >
          Self-host for free
          <ArrowRight01Icon width={14} height={14} />
        </Link>
      </div>
    </div>
  );
}
