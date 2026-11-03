"use client";

import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import { formatMoney } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  type PaywallConceptProps,
  PRICE_CURRENCY,
} from "../labData";
import { NEED_COPY } from "../needCopy";
import { PriceDock } from "./PriceDock";
import { ValueHeadline } from "./ValueHeadline";

const WEEKS_PER_MONTH = 52 / 12;
const MINUTES_PER_HOUR = 60;

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  const rest = minutes % MINUTES_PER_HOUR;
  if (!hours) return `${rest}m`;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

/** Concept 3: no connect. The jobs GAIA takes from their two answers, as a ledger of time returned. */
export function WeekBack({ subject, onCheckout }: PaywallConceptProps) {
  const jobs = subject.needs.map((need) => NEED_COPY[need]);
  const weeklyMinutes = jobs.reduce((sum, job) => sum + job.minutesPerWeek, 0);
  const monthlyHours = (weeklyMinutes * WEEKS_PER_MONTH) / MINUTES_PER_HOUR;
  const pricePerHour = formatMoney(
    Math.round(MONTHLY_PRICE_MINOR / monthlyHours),
    PRICE_CURRENCY,
  );
  const drafted = subject.startingJobs.length;

  return (
    <m.div className="flex flex-1 flex-col gap-6" {...MOTION_FADE_UP}>
      <ValueHeadline
        headline={`Here's ${formatDuration(weeklyMinutes)} of your week back.`}
        line={`${jobs.length === 1 ? "One job" : `${jobs.length} jobs`} I take off your plate from today, from what you just told me.`}
      />

      <div className="rounded-2xl bg-zinc-800 p-4">
        <ol className="flex flex-col gap-2">
          {jobs.map((job) => (
            <li
              key={job.job}
              className="flex items-start justify-between gap-4 rounded-xl bg-zinc-900 p-3"
            >
              <div className="min-w-0">
                <p className="text-sm leading-relaxed text-zinc-100">
                  {job.job}
                </p>
                <p className="mt-1 text-[13px] text-zinc-500">{job.cadence}</p>
              </div>
              <span className="shrink-0 text-sm font-medium text-zinc-200 tabular-nums">
                {formatDuration(job.minutesPerWeek)}
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-3 flex items-baseline justify-between gap-4 px-3">
          <p className="text-sm text-zinc-400">Back every week</p>
          <p className="text-base font-semibold text-zinc-100 tabular-nums">
            {formatDuration(weeklyMinutes)}
          </p>
        </div>
      </div>

      <p className="text-[13px] leading-relaxed text-zinc-500">
        {drafted > 0
          ? `${drafted} of these ${drafted === 1 ? "is" : "are"} already drafted and run the minute you're in. `
          : ""}
        Times are what these take by hand. At {Math.round(monthlyHours)} hours a
        month, I cost you {pricePerHour} an hour.
      </p>

      <PriceDock keepLabel="Take them off my plate" onCheckout={onCheckout} />
    </m.div>
  );
}
