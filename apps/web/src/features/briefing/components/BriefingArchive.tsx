"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import type { BriefingView } from "@shared/api/generated";
import {
  endOfWeek,
  format,
  isSameWeek,
  parseISO,
  startOfWeek,
  subWeeks,
} from "date-fns";

import { cn } from "@/lib/utils";

import { useBriefingsQuery } from "../hooks/useBriefingsQuery";
import type { FoldedBriefSummary } from "./BriefCard";
import { BriefingFold } from "./BriefingFold";

const WEEK_OPTIONS = { weekStartsOn: 1 } as const;
const GRID_CLASSES = "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4";

export interface BriefingArchiveProps {
  limit?: number;
  className?: string;
}

interface WeekGroup {
  start: Date;
  briefings: BriefingView[];
}

function foldedBriefOf(briefing: BriefingView): FoldedBriefSummary {
  return {
    headline: briefing.payload.headline,
    date: briefing.date,
    kind: briefing.kind,
    lede: briefing.payload.lede,
    imageUrl: briefing.edition_image_url,
    editionName: briefing.edition_name,
    stampCityName: briefing.stamp_city_name,
    needsYouCount: briefing.needs_you_count,
  };
}

/** Briefs bucketed by Monday-start week, newest week first; the weekly recap leads its week. */
function groupByWeek(briefings: BriefingView[]): WeekGroup[] {
  const groups = new Map<number, WeekGroup>();
  for (const briefing of briefings) {
    const start = startOfWeek(parseISO(briefing.date), WEEK_OPTIONS);
    const group = groups.get(start.getTime()) ?? { start, briefings: [] };
    group.briefings.push(briefing);
    groups.set(start.getTime(), group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    briefings: [...group.briefings].sort(
      (a, b) => Number(b.kind === "weekly") - Number(a.kind === "weekly"),
    ),
  }));
}

function weekTitle(start: Date, now: Date): string | null {
  if (isSameWeek(start, now, WEEK_OPTIONS)) return "This week";
  if (isSameWeek(start, subWeeks(now, 1), WEEK_OPTIONS)) return "Last week";
  return null;
}

function WeekHeader({ start }: { start: Date }) {
  const range = `${format(start, "MMM d")} – ${format(endOfWeek(start, WEEK_OPTIONS), "MMM d")}`;
  const title = weekTitle(start, new Date());
  return (
    <h2 className="mb-2.5 flex items-baseline justify-between text-sm font-medium text-zinc-200">
      {title ?? range}
      {title && (
        <span className="text-xs font-normal text-zinc-500">{range}</span>
      )}
    </h2>
  );
}

/** Every brief folded to a letter card, grouped by week, newest first; each unfolds above the page. */
export function BriefingArchive({
  limit = 30,
  className,
}: BriefingArchiveProps) {
  const {
    data: briefings,
    isLoading,
    isError,
    refetch,
  } = useBriefingsQuery(limit);

  if (isLoading) {
    return (
      <div className={cn(GRID_CLASSES, className)}>
        <Skeleton className="aspect-square w-full rounded-2xl" />
        <Skeleton className="aspect-square w-full rounded-2xl" />
        <Skeleton className="aspect-square w-full rounded-2xl" />
        <Skeleton className="aspect-square w-full rounded-2xl" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-3">
        <p className="text-sm text-zinc-500">Couldn't load your briefings.</p>
        <Button size="sm" variant="flat" onPress={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (!briefings || briefings.length === 0) {
    return <p className="text-sm text-zinc-500">No past briefings yet.</p>;
  }

  return (
    <div className={cn("flex flex-col gap-8", className)}>
      {groupByWeek(briefings).map((group) => (
        <section key={group.start.getTime()}>
          <WeekHeader start={group.start} />
          <div className={GRID_CLASSES}>
            {group.briefings.map((briefing) => {
              const isWeekly = briefing.kind === "weekly";
              return (
                <div
                  key={briefing.id}
                  className={cn(isWeekly && "col-span-full")}
                >
                  <BriefingFold
                    brief={foldedBriefOf(briefing)}
                    variant={isWeekly ? "feature" : "card"}
                    payload={briefing.payload}
                  />
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
