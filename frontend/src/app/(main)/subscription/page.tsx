"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";

import { PaymentSummary } from "@/features/pricing/components/PaymentSummary";
import { PricingCards } from "@/features/pricing/components/PricingCards";

export default function SubscriptionPage() {
  return (
    <div className="container mx-auto space-y-8 px-4 py-8">
      <div className="space-y-4 text-center">
        <Chip color="primary" size="lg" variant="light">
          Subscription Management
        </Chip>

        <h1 className="text-4xl font-bold">Manage Your GAIA Subscription</h1>
        <p className="text-lg text-default-600">
          View your current plan and upgrade or downgrade as needed
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <PaymentSummary />
        </div>

        <div className="lg:col-span-2">
          <div className="space-y-6">
            <h2 className="text-center text-2xl font-semibold">
              Available Plans
            </h2>

            <Tabs
              aria-label="Options"
              radius="full"
              className="flex justify-center"
            >
              <Tab key="monthly" title="Monthly">
                <PricingCards durationIsMonth />
              </Tab>
              <Tab
                key="yearly"
                title={
                  <div className="flex items-center gap-2">
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
        </div>
      </div>
    </div>
  );
}
