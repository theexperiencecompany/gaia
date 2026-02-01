"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import Image from "next/image";

import { wallpapers } from "@/config/wallpapers";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { ComparisonTable } from "@/features/pricing/components/ComparisonTable";
import { PricingCards } from "@/features/pricing/components/PricingCards";

import type { Plan } from "../api/pricingApi";
import { FAQAccordion } from "./FAQAccordion";

interface PricingPageProps {
  initialPlans?: Plan[];
}

const integrations = [
  { id: "gmail", name: "Gmail" },
  { id: "slack", name: "Slack" },
  { id: "notion", name: "Notion" },
  { id: "googlecalendar", name: "Google Calendar" },
  { id: "github", name: "GitHub" },
  { id: "googlesheets", name: "Google Sheets" },
  { id: "todoist", name: "Todoist" },
  { id: "linear", name: "Linear" },
  { id: "asana", name: "Asana" },
  { id: "trello", name: "Trello" },
];

export default function PricingPage({ initialPlans = [] }: PricingPageProps) {
  return (
    <div className="flex min-h-screen w-screen flex-col items-center justify-center pt-[35vh]">
      <div className="fixed inset-0 top-0 z-0 h-[90vh] w-full">
        <Image
          src={wallpapers.pricing.webp}
          alt="GAIA Pricing page Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-bottom opacity-65"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-linear-to-t from-background via-background to-transparent" />
      </div>

      <div className="relative z-1 flex flex-col items-center gap-2">
        <div className="flex w-full flex-col items-center justify-center gap-3 text-white">
          <h1 className="font-serif text-8xl font-normal">Level Up</h1>
          <span className="text-xl font-light text-zinc-300">
            Choose the plan that matches your ambition
          </span>
        </div>

        <div className="mt-5 flex w-full flex-col items-center font-medium">
          <Tabs aria-label="Options" radius="full">
            <Tab key="monthly" title="Monthly">
              <PricingCards durationIsMonth initialPlans={initialPlans} />
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
              <PricingCards initialPlans={initialPlans} />
            </Tab>
          </Tabs>
        </div>

        <ComparisonTable
          integrations={integrations}
          isLoading={false}
          hasMessages={false}
        />

        <div className="relative mb-10 w-full max-w-7xl overflow-hidden rounded-4xl bg-zinc-900/50 px-8 backdrop-blur-sm">
          <FAQAccordion />
        </div>

        <FinalSection />
      </div>
    </div>
  );
}
