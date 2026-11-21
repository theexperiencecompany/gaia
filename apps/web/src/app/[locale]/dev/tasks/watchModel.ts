import {
  addDays,
  differenceInCalendarDays,
  differenceInMinutes,
  format,
  parseISO,
} from "date-fns";

import type {
  BlindReason,
  Task,
  TaskEnds,
  TaskWatch,
  TaskWhen,
  WatchRung,
} from "./taskModel";

/** Every watch ends by its expiry, this many days after it is set up. */
export const WATCH_EXPIRY_DAYS = 90;
/** The hour a "reply by" deadline falls at on its day. */
export const DEADLINE_HOUR = 17;

/** A watch that can't see its value for this long pauses itself. */
export const BLIND_PAUSE_HOURS = 72;

/** The fastest each source may be read, in minutes (the plan's cadence floors). */
const CADENCE_FLOOR: Record<WatchRung, number> = {
  connector: 1,
  api: 1,
  feed: 1,
  page: 15,
  browser: 30,
  agent: 60,
};

/** An open watch has no single source, so it is one look a day. */
const OPEN_EVERY = 1440;

const CADENCES = [1, 15, 60, 360, 1440];

export function cadenceLabel(minutes: number): string {
  if (minutes >= 1440) return "Once a day";
  if (minutes >= 60) {
    const hours = minutes / 60;
    return hours === 1 ? "Every hour" : `Every ${hours} hours`;
  }
  return minutes === 1 ? "Every minute" : `Every ${minutes} min`;
}

/** The speeds a watch can be checked at, from its source's floor up. */
export function cadenceChoices(watch: TaskWatch): number[] {
  if (watch.kind === "open") return [OPEN_EVERY];
  const floor = CADENCE_FLOOR[watch.source.rung];
  return CADENCES.filter((minutes) => minutes >= floor);
}

/** "$50", "150,000 USD": the unit leads when it is a symbol. */
export function amount(value: number, unit = ""): string {
  const number = value.toLocaleString("en-US");
  return unit.length === 1 ? `${unit}${number}` : `${number} ${unit}`.trim();
}

/** "Fri", "Dec 2": a deadline as it reads in a short line. */
function shortDay(iso: string): string {
  const away = differenceInCalendarDays(parseISO(iso), new Date());
  return away >= 0 && away < 7
    ? format(parseISO(iso), "EEE")
    : format(parseISO(iso), "MMM d");
}

/** What a watch looks for, as one short line: "Billy bookcase under $50". */
function watchLabel(watch: TaskWatch): string {
  const { condition, source } = watch;
  switch (watch.kind) {
    case "threshold":
      return `${source.label} ${condition.direction === "above" ? "over" : "under"} ${amount(condition.value ?? 0, condition.unit)}`;
    case "state":
      return `${source.label}: ${condition.target ?? "any change"}`;
    case "new_items":
      return condition.items ?? source.label;
    case "uptime":
      return `${source.label} goes down`;
    case "reply_by":
      return `Reply from ${condition.from} by ${shortDay(condition.deadline ?? "")}`;
    case "open":
      return source.label;
  }
}

/** A watch, as the When a task carries; its label is built from it. */
export function onWatch(watch: TaskWatch, ends?: TaskEnds): TaskWhen {
  return {
    kind: "watch",
    watch,
    app: watch.source.app,
    label: watchLabel(watch),
    ends,
  };
}

/** Where a fresh watch ends: by its expiry, 90 days from now. */
export const freshExpiry = () =>
  addDays(new Date(), WATCH_EXPIRY_DAYS).toISOString();

/** Scraped values and up/down need a second read a minute later; code decides, not the model. */
export const needsSecondRead = (watch: Pick<TaskWatch, "kind" | "source">) =>
  watch.kind === "uptime" ||
  watch.source.rung === "page" ||
  watch.source.rung === "browser";

/** "just now", "12 min ago", "3 hours ago", "yesterday", "Nov 18". */
export function ago(iso: string): string {
  const minutes = differenceInMinutes(new Date(), parseISO(iso));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const days = differenceInCalendarDays(new Date(), parseISO(iso));
  if (days === 0) {
    const hours = Math.round(minutes / 60);
    return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  }
  if (days === 1) return "yesterday";
  return format(parseISO(iso), "MMM d");
}

/** Why GAIA can't see it, in a sentence, and the one fix it suggests. */
export const BLIND: Record<
  BlindReason,
  { line: (where: string) => string; fix: "connect" | "retry" | "change" }
> = {
  signed_out: {
    line: (where) => `GAIA was signed out of ${where}, so it can't see this.`,
    fix: "connect",
  },
  blocked: {
    line: (where) => `${where} turned GAIA away, so it can't see this.`,
    fix: "retry",
  },
  page_changed: {
    line: (where) =>
      `The page on ${where} changed and GAIA can't find this on it.`,
    fix: "change",
  },
};

/** The reading and when it was taken, as the Status row says it. */
export function watchStatus(task: Task): string | undefined {
  const watch = task.when.watch;
  if (!watch) return undefined;
  if (watch.ended) return watch.ended.why;
  if (!watch.reading) return undefined;
  return `${watch.reading.value}, checked ${ago(watch.reading.at)}.`;
}

/** How a watch's end reads on its row: after an alert, on a date, or by its expiry. */
export function watchEndsLabel(when: TaskWhen): string | undefined {
  const watch = when.watch;
  if (!watch || watch.ended) return undefined;
  const { ends } = when;
  if (watch.kind === "reply_by") return `When ${watch.condition.from} replies`;
  if (ends?.afterRuns === 1) return "After it tells you";
  if (ends?.afterRuns) return `${watch.alerts} of ${ends.afterRuns} alerts`;
  const last = ends?.onDate ?? watch.expiresAt;
  return `Until ${format(parseISO(last), "MMM d")}`;
}
