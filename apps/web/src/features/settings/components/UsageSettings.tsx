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

import { useUsageSummary } from "../hooks/useUsage";
import { CreditBalanceHero } from "./CreditBalanceHero";
import { UsageCatalogModal } from "./UsageCatalogModal";

export default function UsageSettings() {
  const [selectedPeriod, setSelectedPeriod] = useState("day");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const { data: summary, isLoading: summaryLoading } = useUsageSummary();
  const periodLabel =
    selectedPeriod === "day"
      ? "daily"
      : selectedPeriod === "month"
        ? "monthly"
        : `${selectedPeriod}ly`;

  const getProgressColor = (percentage: number) => {
    if (percentage >= 90) return "danger";
    if (percentage >= 70) return "warning";
    return "success";
  };

  if (summaryLoading) {
    return (
      <div className="flex min-h-[80vh] items-center justify-center">
        <Spinner />
      </div>
    );
  }

  // Get features for the selected period. The unified "credits" pool is shown
  // in the balance hero, so exclude it from the per-feature list.
  const featuresWithPeriod = summary
    ? Object.entries(summary.features).filter(
        ([key, feature]) =>
          key !== "credits" &&
          feature.periods[selectedPeriod as keyof typeof feature.periods],
      )
    : [];

  const isPaid = summary?.plan_type === "pro" || summary?.plan_type === "max";

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
          {summary?.plan_type || "free"} plan
        </Chip>
        <Tabs
          selectedKey={selectedPeriod}
          onSelectionChange={(key) => setSelectedPeriod(key as string)}
          size="sm"
        >
          <Tab key="day" title="Daily" />
          <Tab key="month" title="Monthly" />
        </Tabs>
      </div>

      <SettingsSection title="Usage">
        {featuresWithPeriod.length === 0 ? (
          <div className="flex flex-col items-center px-4 py-8 text-center">
            <ChartIcon className="mx-auto h-10 w-10 text-zinc-600" />
            <h3 className="mt-3 text-base font-medium text-white">
              No limits configured
            </h3>
            <p className="mt-1 text-sm text-zinc-500">
              No {periodLabel} limits are configured for your{" "}
              {summary?.plan_type?.toUpperCase()} plan.
            </p>
          </div>
        ) : (
          featuresWithPeriod.map(([key, feature]) => {
            const periodData =
              feature.periods[selectedPeriod as keyof typeof feature.periods];
            if (!periodData) return null;

            return (
              <SettingsRow
                key={key}
                label={feature.title}
                description={feature.description}
                stacked
              >
                <div className="flex items-center gap-3">
                  <Progress
                    value={periodData.percentage}
                    color={getProgressColor(periodData.percentage)}
                    className="flex-1"
                  />
                  <span
                    className="shrink-0 text-xs text-zinc-500"
                    suppressHydrationWarning
                  >
                    {periodData.used.toLocaleString()} /{" "}
                    {periodData.limit.toLocaleString()}
                  </span>
                </div>
              </SettingsRow>
            );
          })
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
