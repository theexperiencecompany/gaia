"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Progress } from "@heroui/progress";
import { Tab, Tabs } from "@heroui/tabs";
import { ChartIcon } from "@icons";
import { useState } from "react";
import Spinner from "@/components/ui/spinner";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { usePricingModalStore } from "@/stores/pricingModalStore";

import { useCreditBalance } from "../hooks/useUsage";
import { CreditBalanceHero } from "./CreditBalanceHero";
import { UsageCatalogModal } from "./UsageCatalogModal";

export default function UsageSettings() {
  const [selectedPeriod, setSelectedPeriod] = useState<"day" | "month">("day");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const { data: balance, isLoading } = useCreditBalance();
  const periodLabel = selectedPeriod === "day" ? "today" : "this month";

  if (isLoading) {
    return (
      <div className="flex min-h-[80vh] items-center justify-center">
        <Spinner />
      </div>
    );
  }

  // Credits spent per feature this period (the unified balance is in the hero).
  const breakdown = balance?.periods[selectedPeriod]?.breakdown ?? [];
  const maxCredits = Math.max(1, ...breakdown.map((row) => row.credits));
  const isPaid = balance?.plan_type === "pro" || balance?.plan_type === "max";

  return (
    <SettingsPage>
      {/* Credit balance — the headline */}
      <CreditBalanceHero />

      {/* Upgrade CTA — only for free plan */}
      {!isPaid && (
        <SettingsSection title="Upgrade">
          <div className="px-4 py-4">
            <p className="mb-3 text-sm text-primary">
              Get 25-250x higher usage limits across all features, priority
              support, and private Discord channels.
            </p>
            <div className="flex w-full justify-end">
              <Button
                color="primary"
                className="font-medium"
                size="sm"
                onPress={openPricingModal}
              >
                Upgrade Now
              </Button>
            </div>
          </div>
        </SettingsSection>
      )}

      {/* Period selector + plan chip */}
      <div className="flex items-center justify-between">
        <Chip
          size="sm"
          color={isPaid ? "primary" : "default"}
          className="font-medium capitalize"
        >
          {balance?.plan_type || "free"} plan
        </Chip>
        <Tabs
          selectedKey={selectedPeriod}
          onSelectionChange={(key) => setSelectedPeriod(key as "day" | "month")}
          size="sm"
        >
          <Tab key="day" title="Daily" />
          <Tab key="month" title="Monthly" />
        </Tabs>
      </div>

      <SettingsSection title="Where your credits went">
        {breakdown.length === 0 ? (
          <div className="flex flex-col items-center px-4 py-8 text-center">
            <ChartIcon className="mx-auto h-10 w-10 text-zinc-600" />
            <h3 className="mt-3 text-base font-medium text-white">
              No usage {periodLabel}
            </h3>
            <p className="mt-1 text-sm text-zinc-500">
              Once you use GAIA, you'll see which features spent your credits.
            </p>
          </div>
        ) : (
          breakdown.map((row) => (
            <SettingsRow key={row.key} label={row.title} stacked>
              <div className="flex items-center gap-3">
                <Progress
                  value={(row.credits / maxCredits) * 100}
                  color="primary"
                  className="flex-1"
                />
                <span
                  className="shrink-0 text-xs text-zinc-500"
                  suppressHydrationWarning
                >
                  {row.credits.toLocaleString()} credits
                </span>
              </div>
            </SettingsRow>
          ))
        )}
      </SettingsSection>

      <div className="flex justify-center">
        <Button
          size="sm"
          variant="light"
          className="text-zinc-400"
          onPress={() => setCatalogOpen(true)}
        >
          What uses credits?
        </Button>
      </div>

      <UsageCatalogModal
        isOpen={catalogOpen}
        onClose={() => setCatalogOpen(false)}
      />
    </SettingsPage>
  );
}
