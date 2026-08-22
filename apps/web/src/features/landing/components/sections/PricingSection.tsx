"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import { ArrowRight02Icon } from "@icons";
import Link from "next/link";
import { useState } from "react";

import { PricingCards } from "@/features/pricing/components/PricingCards";
import LargeHeader from "../shared/LargeHeader";

export default function PricingSection() {
  const [isYearly, setIsYearly] = useState(false);

  return (
    <section className="flex w-full flex-col items-center px-4 py-16 sm:px-6 sm:py-24">
      <LargeHeader
        chipText="Pricing"
        headingText="$1 a day to never work again."
        subHeadingText="Free to start. The cheapest hire you'll ever make."
        centered
      />

      <div className="mt-8 flex w-full flex-col items-center gap-6">
        <Tabs
          selectedKey={isYearly ? "yearly" : "monthly"}
          onSelectionChange={(key) => setIsYearly(key === "yearly")}
          radius="full"
          size="lg"
          aria-label="Billing period"
        >
          <Tab key="monthly" title="Monthly" />
          <Tab
            key="yearly"
            title={
              <div className="flex items-center gap-2">
                Yearly
                <Chip color="primary" size="sm" variant="solid">
                  Save 25%
                </Chip>
              </div>
            }
          />
        </Tabs>

        <PricingCards durationIsMonth={!isYearly} hideEnterprise />

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
