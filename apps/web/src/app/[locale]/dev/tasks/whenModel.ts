import {
  addDays,
  differenceInCalendarDays,
  format,
  getDate,
  getDay,
  parseISO,
} from "date-fns";

import { describeCron } from "@/features/workflows/utils/cronUtils";
import { DEMO_TRIGGERS } from "./demoTriggers";
import type { TaskEnds, TaskWhen, TriggerData } from "./taskModel";

export const NO_WHEN: TaskWhen = { kind: "anytime" };

/** "8 AM", "9:45 AM": the minutes only when there are some. */
function clock(hour: number, minute: number): string {
  const suffix = hour >= 12 ? "PM" : "AM";
  const hour12 = hour % 12 === 0 ? 12 : hour % 12;
  const minutes = minute ? `:${String(minute).padStart(2, "0")}` : "";
  return `${hour12}${minutes} ${suffix}`;
}

function dayLabel(date: Date, daysAway: number): string {
  if (daysAway === 0) return "Today";
  if (daysAway === 1) return "Tomorrow";
  if (daysAway === -1) return "Yesterday";
  if (daysAway > 1 && daysAway < 7) return format(date, "EEE");
  return format(date, "MMM d");
}

/** Once, on a date, with a time of day when one is set. */
export function onDate(date: Date, time?: string): TaskWhen {
  const order = differenceInCalendarDays(date, new Date());
  const day = dayLabel(date, order);
  const [hour, minute] = (time ?? "").split(":").map(Number);
  return {
    kind: "at",
    date: format(date, "yyyy-MM-dd"),
    time,
    label: time ? `${day}, ${clock(hour, minute)}` : day,
    order,
    isToday: order === 0,
    overdue: order < 0,
  };
}

export const inDays = (days: number, time?: string) =>
  onDate(addDays(new Date(), days), time);

/** A repeat the picker can show; any other cron stays a cron expression. */
export interface Repeat {
  every: "day" | "week" | "month";
  /** Week: days it runs on, 0 is Sunday. */
  days: number[];
  dayOfMonth: number;
  hour: number;
  minute: number;
}

export const DEFAULT_REPEAT: Repeat = {
  every: "day",
  days: [1],
  dayOfMonth: 1,
  hour: 9,
  minute: 0,
};

const WHOLE = /^\d+$/;

/** "1-5" or "1,3,5" as day numbers, or null when it is anything else. */
function readDays(field: string): number[] | null {
  const days = new Set<number>();
  for (const part of field.split(",")) {
    const [from, to = from] = part.split("-");
    if (!WHOLE.test(from) || !WHOLE.test(to)) return null;
    for (let day = Number(from); day <= Number(to); day++) days.add(day % 7);
  }
  return [...days].sort((a, b) => a - b);
}

function writeDays(days: number[]): string {
  const sorted = [...days].sort((a, b) => a - b);
  const isRun = sorted.every((day, i) => i === 0 || day === sorted[i - 1] + 1);
  return isRun && sorted.length > 2
    ? `${sorted[0]}-${sorted.at(-1)}`
    : sorted.join(",");
}

export function toCron(repeat: Repeat): string {
  const at = `${repeat.minute} ${repeat.hour}`;
  if (repeat.every === "week") return `${at} * * ${writeDays(repeat.days)}`;
  if (repeat.every === "month") return `${at} ${repeat.dayOfMonth} * *`;
  return `${at} * * *`;
}

export function fromCron(cron: string): Repeat | null {
  const [minute, hour, dayOfMonth, month, dayOfWeek, ...rest] = cron
    .trim()
    .split(/\s+/);
  if (rest.length > 0 || month !== "*") return null;
  if (!WHOLE.test(minute ?? "") || !WHOLE.test(hour ?? "")) return null;
  const at = { hour: Number(hour), minute: Number(minute) };
  if (dayOfMonth === "*" && dayOfWeek === "*") {
    return { ...DEFAULT_REPEAT, ...at, every: "day" };
  }
  if (dayOfMonth === "*") {
    const days = readDays(dayOfWeek);
    return days && { ...DEFAULT_REPEAT, ...at, every: "week", days };
  }
  if (dayOfWeek === "*" && WHOLE.test(dayOfMonth)) {
    return {
      ...DEFAULT_REPEAT,
      ...at,
      every: "month",
      dayOfMonth: Number(dayOfMonth),
    };
  }
  return null;
}

const SHORT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAYS = [
  "Sundays",
  "Mondays",
  "Tuesdays",
  "Wednesdays",
  "Thursdays",
  "Fridays",
  "Saturdays",
];

function weekLabel(days: number[]): string {
  const key = days.join("");
  if (key === "0123456") return "Every day";
  if (key === "12345") return "Weekdays";
  if (key === "06") return "Weekends";
  if (days.length === 1) return DAYS[days[0]];
  return days.map((day) => SHORT_DAYS[day]).join(", ");
}

function repeatLabel(repeat: Repeat): string {
  const at = clock(repeat.hour, repeat.minute);
  if (repeat.every === "week") return `${weekLabel(repeat.days)}, ${at}`;
  if (repeat.every === "month") {
    const day = format(new Date(2024, 0, repeat.dayOfMonth), "do");
    return `Monthly on the ${day}, ${at}`;
  }
  return `Every day, ${at}`;
}

/** Days until the repeat next falls due, counting today while its time is still ahead. */
function daysUntilNext(repeat: Repeat): number | undefined {
  const now = new Date();
  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const isAhead = repeat.hour * 60 + repeat.minute > minutesNow;
  for (let ahead = isAhead ? 0 : 1; ahead <= 31; ahead++) {
    const day = addDays(now, ahead);
    if (repeat.every === "day") return ahead;
    if (repeat.every === "week" && repeat.days.includes(getDay(day)))
      return ahead;
    if (repeat.every === "month" && getDate(day) === repeat.dayOfMonth)
      return ahead;
  }
  return undefined;
}

/** On repeat: the cron the workflow trigger stores, in the timezone it runs in. */
export function onSchedule(cron: string, timezone: string): TaskWhen {
  const repeat = fromCron(cron);
  return {
    kind: "schedule",
    cron,
    timezone,
    label: repeat ? repeatLabel(repeat) : (describeCron(cron) ?? cron),
    order: repeat ? daysUntilNext(repeat) : undefined,
  };
}

/** When something happens in an app, with its settings and an optional "only when". */
export function onEvent(
  trigger: string,
  condition?: string,
  triggerData?: TriggerData,
): TaskWhen {
  const known = DEMO_TRIGGERS.find((item) => item.slug === trigger);
  return {
    kind: "event",
    trigger,
    app: known?.app,
    triggerData,
    condition: condition?.trim() ? condition : undefined,
    label: known?.name ?? trigger,
  };
}

/** How a limit reads on its row: "3 of 10 runs", or the last day it runs. */
export function endsLabel(ends: TaskEnds, runCount = 0): string | undefined {
  if (ends.afterRuns) return `${runCount} of ${ends.afterRuns} runs`;
  if (ends.onDate) return `Until ${format(parseISO(ends.onDate), "MMM d")}`;
  return undefined;
}

/** A next check as it reads mid-sentence: "later today", "tomorrow", "Friday", "Dec 2". */
export function checkDay(iso: string): string {
  const date = parseISO(iso);
  const away = differenceInCalendarDays(date, new Date());
  if (away <= 0) return `today at ${clock(date.getHours(), date.getMinutes())}`;
  if (away === 1) return "tomorrow";
  if (away < 7) return format(date, "EEEE");
  return format(date, "MMM d");
}
