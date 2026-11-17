"use client";

import { Skeleton } from "@heroui/react";
import { News01Icon } from "@icons";
import type { BriefingView } from "@shared/api/generated";
import {
  endOfWeek,
  format,
  isSameWeek,
  isSameYear,
  parseISO,
  startOfWeek,
  subWeeks,
} from "date-fns";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { LinkButton } from "@/components/shared/LinkButton";
import { LoadError } from "@/components/shared/LoadError";
import { cn } from "@/lib/utils";

import { BRIEFINGS_SETTINGS_PATH } from "../constants";
import { useBriefingsQuery } from "../hooks/useBriefingsQuery";
import type { FoldedBriefSummary } from "./BriefCard";
import { BriefingFold } from "./BriefingFold";

const WEEK_OPTIONS = { weekStartsOn: 1 } as const;
/** The page is an @container; columns follow its width, as on the workflows page. */
const GRID_CLASSES =
  "grid grid-cols-2 gap-3 @3xl:grid-cols-3 @5xl:grid-cols-4 @7xl:grid-cols-5";
const SKELETON_KEYS = ["first", "second", "third", "fourth"];

export interface BriefingArchiveProps {
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
    imageUrl: briefing.edition_image_url,
    editionFold: briefing.edition_fold,
    editionPaper: briefing.edition_paper,
    editionName: briefing.edition_name,
    stampCityName: briefing.stamp_city_name,
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

function weekRange(start: Date, now: Date): string {
  const end = endOfWeek(start, WEEK_OPTIONS);
  const range = `${format(start, "MMM d")} – ${format(end, "MMM d")}`;
  return isSameYear(end, now) ? range : `${range}, ${format(end, "yyyy")}`;
}

/** Pinned while its week scrolls by, so the reader always knows which week they are in. */
function WeekHeader({ start }: { start: Date }) {
  const now = new Date();
  const range = weekRange(start, now);
  const title = weekTitle(start, now);
  return (
    <header className="sticky top-0 z-10 flex items-baseline gap-3 bg-primary-bg py-3">
      <h2 className="text-base font-medium text-zinc-100">{title ?? range}</h2>
      {title && <span className="text-xs text-zinc-500">{range}</span>}
    </header>
  );
}

/** No brief has arrived yet: what this page will hold, and where to set when they come. */
function ArchiveEmpty() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-900 px-6 py-14 text-center">
      <span className="flex size-11 items-center justify-center rounded-2xl bg-zinc-800">
        <News01Icon className="size-5 text-zinc-400" />
      </span>
      <p className="text-sm font-medium text-zinc-100">No briefs yet</p>
      <p className="max-w-xs text-sm text-pretty text-zinc-500">
        Every brief GAIA sends you is filed here by week, ready to unfold again.
      </p>
      <LinkButton
        href={BRIEFINGS_SETTINGS_PATH}
        size="sm"
        variant="default-soft"
        className="mt-1"
      >
        Set your brief schedule
      </LinkButton>
    </div>
  );
}

/**
 * Every brief as the same folded card, titled only, grouped by week, newest first, the
 * weekly recap leading its week; each unfolds above the page.
 */
export function BriefingArchive({ className }: BriefingArchiveProps) {
  const {
    data,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useBriefingsQuery();
  const briefings = data?.pages.flatMap((page) => page.briefings);

  if (isLoading) {
    return (
      <div className={cn(GRID_CLASSES, className)}>
        {SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className="aspect-[4/5] w-full rounded-2xl" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <LoadError
        layout="inline"
        title="Couldn't load your briefings."
        onRetry={() => void refetch()}
      />
    );
  }

  if (!briefings || briefings.length === 0) {
    return <ArchiveEmpty />;
  }

  return (
    <div className={cn("flex flex-col gap-10", className)}>
      {groupByWeek(briefings).map((group) => (
        <section key={group.start.getTime()}>
          <WeekHeader start={group.start} />
          <ul className={GRID_CLASSES}>
            {group.briefings.map((briefing) => (
              <li key={briefing.id}>
                <BriefingFold
                  brief={foldedBriefOf(briefing)}
                  payload={briefing.payload}
                  briefingId={briefing.id}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {hasNextPage && (
        <GaiaButton
          size="sm"
          variant="default-soft"
          className="self-center"
          isPending={isFetchingNextPage}
          onPress={() => void fetchNextPage()}
        >
          Show older briefs
        </GaiaButton>
      )}
    </div>
  );
}
