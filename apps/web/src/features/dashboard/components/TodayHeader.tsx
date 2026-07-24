"use client";

import type React from "react";
import { Fragment } from "react";
import type { TodayRuns, TodaySubline } from "@/types/features/dashboardTypes";

import { formatClockTime } from "../utils/time";

interface TodayHeaderProps {
  headline: string;
  subline: TodaySubline;
  runs: TodayRuns | null;
}

function Dot() {
  return <span className="size-[3px] rounded-full bg-zinc-700" />;
}

/** "Thursday, July 10" — full weekday for the kicker (local, no TZ shift). */
function formatKickerDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (!year || !month || !day) return dateStr;
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/**
 * Date kicker, then the briefing headline as the page title — the morning
 * push and this page share one sentence by construction (deterministic
 * fallback after noon).
 */
export const TodayHeader: React.FC<TodayHeaderProps> = ({
  headline,
  subline,
  runs,
}) => {
  const nextEventTime = subline.next_event
    ? formatClockTime(subline.next_event.time)
    : "";

  // Dot-separated segments: dots sit between present items only, so the last
  // segment never trails a dangling separator.
  const segments: { id: string; node: React.ReactNode }[] = [];
  if (subline.needs_you > 0) {
    segments.push({
      id: "needs-you",
      node: (
        <span className="font-medium text-amber-400/90">
          {subline.needs_you} need{subline.needs_you === 1 ? "s" : ""} you
        </span>
      ),
    });
  }
  if (subline.next_event) {
    segments.push({
      id: "next-event",
      node: (
        <span className="truncate">
          {nextEventTime ? `${nextEventTime} ` : ""}
          {subline.next_event.title}
        </span>
      ),
    });
  }
  if (runs) {
    segments.push({
      id: "runs",
      node: (
        <span>
          {Math.max(0, runs.limit - runs.used)}/{runs.limit} runs left
        </span>
      ),
    });
  }

  return (
    <header className="px-3">
      <p className="text-[13px] font-medium text-zinc-500">
        {formatKickerDate(subline.date)}
      </p>
      <h1 className="mt-2 text-[26px] leading-tight font-semibold tracking-tight text-balance text-zinc-100">
        {headline}
      </h1>
      {segments.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5 text-[13px] text-zinc-500 tabular-nums">
          {segments.map((segment, index) => (
            <Fragment key={segment.id}>
              {index > 0 && <Dot />}
              {segment.node}
            </Fragment>
          ))}
        </div>
      )}
    </header>
  );
};
