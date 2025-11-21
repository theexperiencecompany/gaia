"use client";

import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Progress } from "@heroui/progress";
import { Tab, Tabs } from "@heroui/tabs";
import Link from "next/link";
import { useState } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import { SettingsCard } from "@/features/settings/components/SettingsCard";
import { BarChart3, CalendarIcon, TrendingUp } from "@/icons";

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
    <div className="mx-auto max-w-6xl space-y-6">
      {/* Upgrade to Pro Header */}
      {summary?.plan_type !== "pro" && (
        <SettingsCard
          title="Upgrade to Pro"
          className="border border-primary/70 bg-primary/10!"
        >
          <p className="mb-3 text-sm text-primary">
            Get 25-250x higher usage limits across all features, priority
            support, and private Discord channels.
          </p>
          <div className="flex w-full justify-end">
            <Link href={"/pricing"}>
              <Button color="primary" className="font-medium" size="sm">
                Upgrade Now
              </Button>
            </Link>
          </div>
        </SettingsCard>
      )}

      {/* Header with Period Selection */}
      <SettingsCard>
        <div className="mb-6 flex items-center justify-between">
          <p className="text-lg font-medium text-zinc-300">Usage</p>
          <div className="flex items-center space-x-3">
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
                    <TrendingUp size={16} />
                    <span>Monthly</span>
                  </div>
                }
              />
            </Tabs>
          </div>
        </div>

        {/* Features List */}
        <div className="space-y-3">
          {featuresWithPeriod.length === 0 ? (
            <Card>
              <CardBody className="py-8 text-center">
                <BarChart3 className="text-muted-foreground/50 mx-auto h-10 w-10" />
                <h3 className="mt-3 text-base font-medium">
                  No limits configured
                </h3>
                <p className="text-muted-foreground mt-1 text-sm">
                  No {selectedPeriod}ly limits are configured for your{" "}
                  {summary?.plan_type?.toUpperCase()} plan.
                </p>
              </CardBody>
            </Card>
          ) : (
            featuresWithPeriod.map(([key, feature]) => {
              const periodData =
                feature.periods[selectedPeriod as keyof typeof feature.periods];
              if (!periodData) return null;

              return (
                <Card
                  key={key}
                  className="border-none bg-zinc-800/60 shadow-none"
                >
                  <CardBody className="p-3">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="mb-2 flex items-start justify-between">
                          <div>
                            <h4 className="text-sm font-normal">
                              {feature.title}
                            </h4>
                            <div className="text-xs font-light text-foreground-400">
                              {feature.description}
                            </div>
                          </div>
                          <Chip
                            className="flex items-center space-x-3 text-foreground-600"
                            size="sm"
                          >
                            {periodData.used.toLocaleString()} /{" "}
                            {periodData.limit.toLocaleString()}
                          </Chip>
                        </div>

                        <Progress
                          value={periodData.percentage}
                          color={getProgressColor(periodData.percentage)}
                        />
                      </div>
                    </div>
                  </CardBody>
                </Card>
              );
            })
          )}
        </div>
      </SettingsCard>
    </div>
  );
}
