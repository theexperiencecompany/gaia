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
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    );
  }

  const days = data?.days ?? [];
  const weeks = toWeekColumns(days);

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-semibold text-zinc-100">Activity</p>
        {typeof data?.streak === "number" && data.streak > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-zinc-400">
            <FireIcon className="size-3.5 text-amber-400" />
            <span className="font-medium text-zinc-200">{data.streak}</span>
            <span>day streak</span>
          </div>
        )}
      </div>
      <div className="overflow-x-auto rounded-2xl bg-zinc-900 p-3">
        <div className="flex w-fit gap-[3px]">
          {weeks.map((week, weekIndex) => (
            <div
              key={`heatmap-week-${weekIndex}`}
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
