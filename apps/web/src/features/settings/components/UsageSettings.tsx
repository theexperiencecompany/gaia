"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { usePricingModalStore } from "@/stores/pricingModalStore";

import {
  useUsageActivity,
  useUsageHistory,
  useUsageSummary,
} from "../hooks/useUsage";
import { UsageView } from "./usage/UsageView";

export default function UsageSettings() {
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const { data: summary, isLoading, refetch } = useUsageSummary();
  const { data: history } = useUsageHistory(30);
  const { data: activity } = useUsageActivity(365);

  if (isLoading) return <UsageSkeleton />;
  // Retries are exhausted by now (see useUsageSummary), so a missing summary is
  // a settled failure, not a slow one. Keeping the skeleton up would shimmer
  // forever with no message and no way out.
  if (!summary) return <UsageError onRetry={() => void refetch()} />;

  return (
    <UsageView
      summary={summary}
      history={history ?? []}
      activity={activity}
      onUpgrade={() => openPricingModal()}
    />
  );
}

function UsageError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3 rounded-2xl bg-zinc-900/60 p-10 text-center">
      <p className="text-sm font-medium text-zinc-200">
        Couldn&apos;t load your usage
      </p>
      <p className="max-w-sm text-xs text-zinc-500">
        Your usage is still being tracked — this page just couldn&apos;t reach
        it. Try again in a moment.
      </p>
      <Button
        size="sm"
        color="primary"
        variant="flat"
        radius="full"
        className="mt-1 font-medium"
        onPress={onRetry}
      >
        Try again
      </Button>
    </div>
  );
}

function UsageSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 pb-4">
      {/* Upgrade banner */}
      <Skeleton className="h-[62px] w-full rounded-2xl" />
      {/* Hero: gauge + copy */}
      <div className="flex items-center gap-5 rounded-2xl bg-zinc-900/60 p-4">
        <Skeleton className="size-32 shrink-0 rounded-full" />
        <div className="flex-1">
          <Skeleton className="h-3.5 w-28 rounded-full" />
          <Skeleton className="mt-2 h-5 w-56 rounded-full" />
          <Skeleton className="mt-3 h-3 w-32 rounded-full" />
        </div>
      </div>
      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-2xl bg-zinc-900/60 p-4">
            <Skeleton className="h-3 w-20 rounded-full" />
            <Skeleton className="mt-3 h-7 w-16 rounded-lg" />
            <Skeleton className="mt-2 h-3 w-24 rounded-full" />
          </div>
        ))}
      </div>
      {/* Monthly trend */}
      <div className="rounded-2xl bg-zinc-900/60 p-5">
        <Skeleton className="h-4 w-44 rounded-full" />
        <Skeleton className="mt-4 aspect-[16/6] w-full rounded-xl" />
      </div>
      {/* Day-by-day + badge */}
      <div className="flex items-stretch gap-4">
        <div className="min-w-0 flex-1 rounded-2xl bg-zinc-900/60 p-5">
          <Skeleton className="h-4 w-28 rounded-full" />
          <Skeleton className="mt-4 h-28 w-full rounded-xl" />
        </div>
        <div className="flex w-44 shrink-0 flex-col items-center rounded-2xl bg-zinc-900/60 p-4">
          <Skeleton className="size-28 rounded-full" />
          <Skeleton className="mt-3 h-4 w-20 rounded-full" />
        </div>
      </div>
      {/* Activity heatmap */}
      <div className="rounded-2xl bg-zinc-900/60 p-5">
        <Skeleton className="h-4 w-64 rounded-full" />
        <Skeleton className="mt-4 h-32 w-full rounded-xl" />
      </div>
      {/* Tools */}
      <div className="rounded-2xl bg-zinc-900/60 p-5">
        <div className="flex items-center justify-between">
          <Skeleton className="h-4 w-16 rounded-full" />
          <Skeleton className="h-6 w-28 rounded-full" />
        </div>
        <div className="mt-4 flex flex-col gap-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="h-3.5 w-32 shrink-0 rounded-full" />
              <Skeleton className="h-1.5 flex-1 rounded-full" />
              <Skeleton className="h-3 w-12 shrink-0 rounded-full" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
