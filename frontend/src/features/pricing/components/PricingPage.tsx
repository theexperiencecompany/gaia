"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";

import FinalSection from "@/features/landing/components/sections/FinalSection";
import { ComparisonTable } from "@/features/pricing/components/ComparisonTable";
import { PricingCards } from "@/features/pricing/components/PricingCards";

import { FAQAccordion } from "./FAQAccordion";
import Image from "next/image";
import LargeHeader from "@/features/landing/components/shared/LargeHeader";
export default function PricingPage() {
  return (
    <div className="flex min-h-screen w-screen flex-col items-center justify-center pt-[40vh]">
      <div className="absolute inset-0 top-0 z-0 h-[65vh] w-[102%]">
        <Image
          src={"/images/wallpapers/space.webp"}
          alt="GAIA Pricing page Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-bottom opacity-80"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-gradient-to-t from-background via-background to-transparent" />
      </div>

      <div className="relative z-[1] flex flex-col items-center gap-2">
        <LargeHeader
          centered
          chipText="Pricing"
          headingText="Level Up"
          subHeadingText="Choose the plan that matches your ambition"
        />

        <div className="mt-5 flex w-full flex-col items-center font-medium">
          <Tabs aria-label="Options" radius="full">
            <Tab key="monthly" title="Monthly">
              <PricingCards durationIsMonth />
            </Tab>
            <Tab
              key="yearly"
              title={
                <div className="flex w-full items-center justify-center gap-2">
                  Yearly
                  <Chip color="primary" size="sm" variant="shadow">
                    <div className="text-sm font-medium">Save 25%</div>
                  </Chip>
                </div>
              }
            >
              <PricingCards />
            </Tab>
          </Tabs>
        </div>

        <ComparisonTable />
        <FAQAccordion />
        <FinalSection />
      </div>
    </div>
  );
}
