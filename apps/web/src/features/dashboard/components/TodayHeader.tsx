"use client";

import Link from "next/link";
import type React from "react";
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

  return (
    <header className="px-3">
      <p className="text-[13px] font-medium text-zinc-500">
        {formatKickerDate(subline.date)}
      </p>
      <h1 className="mt-2 text-[26px] leading-tight font-semibold tracking-tight text-balance text-zinc-100">
        {headline}
      </h1>
      <div className="mt-2.5 flex flex-wrap items-center gap-2.5 text-[13px] text-zinc-500 tabular-nums">
        {subline.needs_you > 0 && (
          <>
            <span className="font-medium text-amber-400/90">
              {subline.needs_you} need{subline.needs_you === 1 ? "s" : ""} you
            </span>
            <Dot />
          </>
        )}
        {subline.next_event && (
          <>
            <span className="truncate">
              {nextEventTime ? `${nextEventTime} ` : ""}
              {subline.next_event.title}
            </span>
            <Dot />
          </>
        )}
        {runs && (
          <>
            <span>
              {Math.max(0, runs.limit - runs.used)}/{runs.limit} runs left
            </span>
            <Dot />
          </>
        )}
        <Link
          href="/briefings"
          className="text-zinc-500 underline decoration-zinc-700 underline-offset-4 transition-colors hover:text-zinc-300"
        >
          Full briefing
        </Link>
      </div>
    </header>
  );
};
