"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Progress } from "@heroui/progress";
import { Tab, Tabs } from "@heroui/tabs";
import { CalendarIcon, ChartIcon, ChartIncreaseIcon } from "@icons";
import Link from "next/link";
import { useState } from "react";
import Spinner from "@/components/ui/spinner";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";

import { useUsageSummary } from "../hooks/useUsage";

export default function UsageSettings() {
  const [selectedPeriod, setSelectedPeriod] = useState("day");
  const { data: summary, isLoading: summaryLoading } = useUsageSummary();

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

  // Get features for the selected period
  const featuresWithPeriod = summary
    ? Object.entries(summary.features).filter(
        ([_, feature]) =>
          feature.periods[selectedPeriod as keyof typeof feature.periods],
      )
    : [];

  return (
    <SettingsPage>
      {/* Upgrade CTA — only for free plan */}
      {summary?.plan_type !== "pro" && (
        <SettingsSection title="Upgrade">
          <div className="px-4 py-4">
            <p className="mb-3 text-sm text-primary">
              Get 25-250x higher usage limits across all features, priority
              support, and private Discord channels.
            </p>
            <div className="flex w-full justify-end">
              <Link href="/pricing">
                <Button color="primary" className="font-medium" size="sm">
                  Upgrade Now
                </Button>
              </Link>
            </div>
          </div>
        </SettingsSection>
      )}

      {/* Period selector + plan chip */}
      <div className="flex items-center justify-between">
        <Chip
          size="sm"
          color={summary?.plan_type === "pro" ? "primary" : "default"}
          className="font-medium"
        >
          {summary?.plan_type?.toUpperCase() || "FREE"} PLAN
        </Chip>
        <Tabs
          selectedKey={selectedPeriod}
          onSelectionChange={(key) => setSelectedPeriod(key as string)}
          size="sm"
        >
          <Tab
            key="day"
            title={
              <div className="flex items-center space-x-2">
                <CalendarIcon size={16} />
                <span>Daily</span>
              </div>
            }
          />
          <Tab
            key="month"
            title={
              <div className="flex items-center space-x-2">
                <ChartIncreaseIcon size={16} />
                <span>Monthly</span>
              </div>
            }
          />
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
              No {selectedPeriod}ly limits are configured for your{" "}
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
                  <span className="shrink-0 text-xs text-zinc-500">
                    {periodData.used.toLocaleString()} /{" "}
                    {periodData.limit.toLocaleString()}
                  </span>
                </div>
              </SettingsRow>
            );
          })
        )}
      </SettingsSection>
    </SettingsPage>
  );
}
