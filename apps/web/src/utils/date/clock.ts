/**
 * How a day or a time of day is written in the brief, its settings and its
 * archive: one place, written in the reader's own locale.
 */
import { format, isToday, isYesterday } from "date-fns";

const HOURS_PER_DAY = 24;

/** A day on its own: "Mon 16 Nov". */
export const DAY_FORMAT = "EEE d MMM";
/** A day inside a range, where the weekday would crowd it: "Nov 16". */
export const RANGE_DAY_FORMAT = "MMM d";
/** A day and its hour: "Mon 16 Nov, 7 AM". */
export const DAY_AND_HOUR_FORMAT = "EEE d MMM, h a";

/** An hour of the day as the reader's locale writes it, like "10 PM" or "22". */
export function formatHour(hour: number, locale?: string): string {
  const at = new Date(2000, 0, 1, hour % HOURS_PER_DAY);
  return new Intl.DateTimeFormat(locale, { hour: "numeric" }).format(at);
}

/** A wall-clock "HH:MM" (a calendar event's start) as the reader's locale writes it. */
export function formatClockTime(hhmm: string): string {
  const [hours, minutes] = hhmm.split(":").map(Number);
  const at = new Date();
  at.setHours(hours, minutes, 0, 0);
  return at.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export const TODAY = "Today";

/** "Today" or "Yesterday" for those days, else the day written out. */
export function relativeDay(date: Date): string {
  if (isToday(date)) return TODAY;
  if (isYesterday(date)) return "Yesterday";
  return format(date, DAY_FORMAT);
}
