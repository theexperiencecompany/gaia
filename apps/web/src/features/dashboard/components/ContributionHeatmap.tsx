"use client";

import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { FireIcon } from "@icons";
import { cn } from "@/lib/utils";
import type {
  DashboardHeatmapResponse,
  HeatmapDay,
} from "@/types/features/dashboardTypes";

interface ContributionHeatmapProps {
  data: DashboardHeatmapResponse | undefined;
  isLoading: boolean;
}

const INTENSITY_BUCKETS = [
  { max: 0, className: "bg-zinc-800" },
  { max: 1, className: "bg-emerald-900/60" },
  { max: 2, className: "bg-emerald-700/70" },
  { max: 4, className: "bg-emerald-500/80" },
  { max: Number.POSITIVE_INFINITY, className: "bg-emerald-400" },
];

function intensityClass(day: HeatmapDay): string {
  const total = day.user_count + day.gaia_count;
  return (
    INTENSITY_BUCKETS.find((bucket) => total <= bucket.max)?.className ??
    INTENSITY_BUCKETS[0].className
  );
}

function toWeekColumns(days: HeatmapDay[]): HeatmapDay[][] {
  if (days.length === 0) return [];
  // Pad the front so the first column starts on a Sunday, matching GitHub's grid.
  const firstDow = new Date(days[0].date).getDay();
  const padded: (HeatmapDay | null)[] = [
    ...Array.from({ length: firstDow }, () => null),
    ...days,
  ];
  const columns: HeatmapDay[][] = [];
  for (let i = 0; i < padded.length; i += 7) {
    const week = padded.slice(i, i + 7);
    columns.push(week.filter((d): d is HeatmapDay => d !== null));
  }
  return columns;
}

export function ContributionHeatmap({
  data,
  isLoading,
}: ContributionHeatmapProps) {
  if (isLoading) {
    return (
      <div className="rounded-2xl bg-zinc-800 p-4">
        <Skeleton className="h-14 rounded-2xl" />
      </div>
    );
  }

  const days = data?.days ?? [];
  const weeks = toWeekColumns(days);

  return (
    <div className="flex flex-wrap items-center gap-4 rounded-2xl bg-zinc-800 p-4">
      <div className="flex shrink-0 items-center gap-2">
        <p className="text-sm font-semibold text-zinc-100">Activity</p>
        {typeof data?.streak === "number" && data.streak > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-400">
            <FireIcon className="size-3" />
            {data.streak}d streak
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1 overflow-x-auto rounded-2xl bg-zinc-900 p-2">
        <div className="flex w-fit gap-[3px]">
          {weeks.map((week) => (
            <div
              key={`heatmap-week-${week[0]?.date ?? "empty"}`}
              className="flex flex-col gap-[3px]"
            >
              {week.map((day) => (
                <Tooltip
                  key={day.date}
                  content={`${day.date} — You ${day.user_count} · GAIA ${day.gaia_count}`}
                >
                  <div
                    className={cn(
                      "size-[11px] rounded-[2px]",
                      intensityClass(day),
                    )}
                  />
                </Tooltip>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
