const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/**
 * The one place dates and times are written for a reader. Every formatter
 * takes the reader's locale (undefined: the runtime's own); text that must read
 * the same on the server and in the browser, or in a bot's message, passes
 * FIXED_LOCALE instead.
 */

/** For text rendered on the server or sent by a bot, where no reader's locale is known. */
export const FIXED_LOCALE = "en-US";

export const TODAY = "Today";
export const YESTERDAY = "Yesterday";
export const TOMORROW = "Tomorrow";

interface FormatOptions {
  locale?: string;
  /** IANA zone the instant is read in; the device's own when unset. */
  timeZone?: string;
}

function toDate(date: string | Date): Date {
  return date instanceof Date ? date : new Date(date);
}

// Building an Intl.DateTimeFormat is costly; one is kept per locale and shape.
const formatters = new Map<string, Intl.DateTimeFormat>();

function dateTimeFormat(
  locale: string | undefined,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = JSON.stringify([locale ?? null, options]);
  let formatter = formatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, options);
    formatters.set(key, formatter);
  }
  return formatter;
}

/** Whole calendar days from today to `date` in the device's zone: -1 yesterday, 1 tomorrow. */
function calendarDaysFromToday(date: Date, now: Date = new Date()): number {
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );
  const startOfDay = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  return Math.round((startOfDay.getTime() - startOfToday.getTime()) / DAY_MS);
}

/** "Today", "Yesterday" or "Tomorrow" for those days, else null. */
export function dayName(
  date: string | Date,
  now: Date = new Date(),
): string | null {
  const days = calendarDaysFromToday(toDate(date), now);
  if (days === 0) return TODAY;
  if (days === -1) return YESTERDAY;
  if (days === 1) return TOMORROW;
  return null;
}

/** An hour of the day as the locale writes it: "10 PM", or "22" in en-GB. */
export function formatHour(hour: number, locale?: string): string {
  const at = new Date(2000, 0, 1, hour % 24);
  return dateTimeFormat(locale, { hour: "numeric" }).format(at);
}

const TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  hour: "numeric",
  minute: "2-digit",
};

/** An instant's time of day: "3:45 PM". */
export function formatTime(
  date: string | Date,
  { locale, timeZone }: FormatOptions = {},
): string {
  return dateTimeFormat(locale, { ...TIME_OPTIONS, timeZone }).format(
    toDate(date),
  );
}

/** A wall-clock "HH:MM" (a calendar event's start) as the locale writes it. */
export function formatClockTime(hhmm: string, locale?: string): string {
  const [hours, minutes] = hhmm.split(":").map(Number);
  return formatTime(new Date(2000, 0, 1, hours, minutes), { locale });
}

/** A span of time, sharing what both ends share: "10:00 – 11:30 AM". */
export function formatTimeRange(
  start: string | Date,
  end: string | Date,
  locale?: string,
): string {
  return dateTimeFormat(locale, TIME_OPTIONS).formatRange(
    toDate(start),
    toDate(end),
  );
}

/** The weekday's name: "Monday", or "Mon" when short. */
export function formatWeekday(
  date: string | Date,
  width: "long" | "short" = "long",
  locale?: string,
): string {
  return dateTimeFormat(locale, { weekday: width }).format(toDate(date));
}

/**
 * Format a date as a relative time string (e.g. "5 minutes ago", "2 hours ago").
 */
export function formatRelativeTime(date: string | Date): string {
  const d = toDate(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / MINUTE_MS);
  const diffHours = Math.floor(diffMs / HOUR_MS);
  const diffDays = Math.floor(diffMs / DAY_MS);

  if (diffSecs < 60) return "just now";
  if (diffMins < 60)
    return `${diffMins} minute${diffMins === 1 ? "" : "s"} ago`;
  if (diffHours < 24)
    return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30)
    return `${Math.floor(diffDays / 7)} week${Math.floor(diffDays / 7) === 1 ? "" : "s"} ago`;
  if (diffDays < 365)
    return `${Math.floor(diffDays / 30)} month${Math.floor(diffDays / 30) === 1 ? "" : "s"} ago`;
  return `${Math.floor(diffDays / 365)} year${Math.floor(diffDays / 365) === 1 ? "" : "s"} ago`;
}

const DATE_FORMATS = {
  /** Jan 5 */
  short: { month: "short", day: "numeric" },
  /** Jan 5, 2025 */
  medium: { year: "numeric", month: "short", day: "numeric" },
  /** January 5, 2025 */
  long: { year: "numeric", month: "long", day: "numeric" },
  /** Jan 5, 2025, 3:00 PM */
  datetime: {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  },
  /** Mon, Jan 5 */
  day: { weekday: "short", month: "short", day: "numeric" },
  /** Monday, January 5 */
  fullDay: { weekday: "long", month: "long", day: "numeric" },
  /** Mon, Jan 5, 3:00 PM */
  dayTime: {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  },
  /** 1/5/2025 */
  numeric: { year: "numeric", month: "numeric", day: "numeric" },
  /** January */
  month: { month: "long" },
  /** Jan */
  shortMonth: { month: "short" },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>;

export type DateFormat = keyof typeof DATE_FORMATS;

/** A date as the locale writes it, in one of the named shapes. */
export function formatDate(
  date: string | Date,
  format: DateFormat = "short",
  { locale, timeZone }: FormatOptions = {},
): string {
  return dateTimeFormat(locale, {
    ...DATE_FORMATS[format],
    timeZone,
  }).format(toDate(date));
}

/** A day by name when it is today, yesterday or tomorrow, else in the given shape. */
export function formatDay(
  date: string | Date,
  format: DateFormat = "day",
  locale?: string,
): string {
  return dayName(date) ?? formatDate(date, format, { locale });
}

/** An inbox row's time: the time today, "Yesterday" within two days, else the date. */
export function formatInboxTime(
  date: string | Date,
  now: Date = new Date(),
  locale?: string,
): string {
  const hoursAgo = (now.getTime() - toDate(date).getTime()) / HOUR_MS;
  if (hoursAgo < 24) return formatTime(date, { locale });
  if (hoursAgo < 48) return YESTERDAY;
  return formatDate(date, "short", { locale });
}

/** Short relative time ("Just now", "5m ago", "Yesterday", "3d ago"), then the date. */
export function formatRelativeDate(
  date: string | Date,
  { now = new Date(), locale, timeZone }: FormatOptions & { now?: Date } = {},
): string {
  const diffMs = now.getTime() - toDate(date).getTime();
  const diffMins = Math.floor(diffMs / MINUTE_MS);
  const diffHours = Math.floor(diffMs / HOUR_MS);
  const diffDays = Math.floor(diffMs / DAY_MS);

  if (diffMs < MINUTE_MS) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return YESTERDAY;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(date, "short", { locale, timeZone });
}

/**
 * Format a date in UTC, for values that are UTC calendar days (e.g. a
 * `YYYY-MM-DD` activity date). `formatDate` renders in the device timezone,
 * which shifts a UTC-midnight date onto the previous/next day for most users —
 * use this whenever the underlying value is a UTC calendar day, not an instant.
 * Formats: "short" (Jul 5), "weekday" (Mon, Jul 5), "month" (Jul).
 */
export function formatDateUTC(
  date: string | Date,
  format: "short" | "weekday" | "month" = "short",
): string {
  const shape = {
    short: "short",
    weekday: "day",
    month: "shortMonth",
  } as const;
  return formatDate(date, shape[format], { timeZone: "UTC" });
}

/**
 * Format a due date in a context-aware way:
 * - overdue dates show "Overdue · <date>"
 * - today shows "Due today"
 * - tomorrow shows "Due tomorrow"
 * - within 7 days shows "Due <weekday>"
 * - otherwise shows "Due <formatted date>"
 */
export function formatDueDate(date: string | Date): string {
  const d = toDate(date);
  const diffDays = calendarDaysFromToday(d);

  if (diffDays < 0) {
    return `Overdue · ${formatDate(d, "short")}`;
  }
  if (diffDays === 0) return "Due today";
  if (diffDays === 1) return "Due tomorrow";
  if (diffDays < 7) {
    return `Due ${formatWeekday(d)}`;
  }
  return `Due ${formatDate(d, "short")}`;
}

/**
 * Return true if the given date is in the past (overdue).
 */
export function isOverdue(date: string | Date): boolean {
  return toDate(date).getTime() < Date.now();
}

export type DueChipTone =
  | "completed"
  | "overdue"
  | "today"
  | "tomorrow"
  | "soon"
  | "later";

/**
 * Classify a todo's due-date chip into a tone bucket: completed → "completed" regardless of
 * date; else by calendar day vs. `now` — past → "overdue", same day → "today", next day →
 * "tomorrow", within 3 days → "soon", further out → "later".
 *
 * Uses calendar-day boundaries in the device-local timezone, so any time on the same day
 * still resolves to "today".
 */
export function getDueChipTone(
  date: string | Date | null | undefined,
  completed: boolean,
): DueChipTone {
  if (completed) return "completed";
  if (!date) return "later";

  const due = toDate(date);
  if (Number.isNaN(due.getTime())) return "later";

  const diffDays = calendarDaysFromToday(due);

  if (diffDays < 0) return "overdue";
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "tomorrow";
  if (diffDays <= 3) return "soon";
  return "later";
}

const CRON_WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

const CRON_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** A cron hour and minute as a bot's message writes it: "9 AM", "9:30 AM". */
function cronTime(hour: string, minute: string): string {
  const h = Number.parseInt(hour, 10);
  const m = Number.parseInt(minute, 10);
  return m === 0
    ? formatHour(h, FIXED_LOCALE)
    : formatClockTime(`${h}:${m}`, FIXED_LOCALE);
}

function plural(count: number, unit: string): string {
  return count === 1 ? `1 ${unit}` : `${count} ${unit}s`;
}

/** "2 hours 5 mins" for under a day, "1 day 3 hours" past it, "4 mins" under an hour. */
function elapsed(diffMs: number): string | null {
  const minutes = Math.floor(diffMs / MINUTE_MS);
  const hours = Math.floor(diffMs / HOUR_MS);
  const days = Math.floor(diffMs / DAY_MS);
  if (days > 0)
    return [plural(days, "day"), hours % 24 ? plural(hours % 24, "hour") : null]
      .filter(Boolean)
      .join(" ");
  if (hours > 0)
    return [
      plural(hours, "hour"),
      minutes % 60 ? plural(minutes % 60, "min") : null,
    ]
      .filter(Boolean)
      .join(" ");
  if (minutes > 0) return plural(minutes, "min");
  return null;
}

/**
 * A chat message's timestamp: how long ago with the time for the last week
 * ("2 hours 5 mins ago (3:04 PM)", "just now (3:04 PM)"), then the date with
 * its time ("10th Jun '25 (3:04 PM)").
 */
export function formatMessageTime(
  value: string | Date,
  now: Date = new Date(),
  locale?: string,
): string {
  const date = toDate(value);
  const diffMs = now.getTime() - date.getTime();
  const time = formatTime(date, { locale }).toUpperCase();
  if (diffMs < 7 * DAY_MS) {
    const ago = elapsed(diffMs);
    return ago ? `${ago} ago (${time})` : `just now (${time})`;
  }
  const month = dateTimeFormat(locale, { month: "short" }).format(date);
  const year = dateTimeFormat(locale, { year: "2-digit" }).format(date);
  const day = date.getDate();
  return `${day}${ordinalSuffix(day)} ${month} '${year} (${time})`;
}

/**
 * The mobile app's shorter message timestamp: "3 mins ago", "1 hour ago" or
 * "just now" for the last week, then "13th Apr '25 (3:45 PM)".
 * Returns an empty string for invalid input.
 */
export function parseRelativeDateLabel(value: string | Date): string {
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  const formattedTime = formatTime(date).toUpperCase();

  if (diffMs < 7 * DAY_MS) {
    const seconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) {
      const label = days === 1 ? "1 day" : `${days} days`;
      return `${label} ago`;
    }
    if (hours > 0) {
      const label = hours === 1 ? "1 hour" : `${hours} hours`;
      return `${label} ago`;
    }
    if (minutes > 0) {
      const label = minutes === 1 ? "1 min" : `${minutes} mins`;
      return `${label} ago`;
    }
    return "just now";
  }

  const month = formatDate(date, "shortMonth");
  const year = dateTimeFormat(undefined, { year: "2-digit" }).format(date);
  const day = date.getDate();
  const suffix = ordinalSuffix(day);
  return `${day}${suffix} ${month} '${year} (${formattedTime})`;
}

function ordinalSuffix(d: number): string {
  if (d > 3 && d < 21) return "th";
  switch (d % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}

/**
 * Convert a 5-field cron expression into a human-readable description.
 * Handles common patterns; falls back to the raw expression for complex cases.
 */
export function parseCronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  // Every minute
  if (
    minute === "*" &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return "Every minute";
  }

  // Every N minutes
  if (
    minute.startsWith("*/") &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    const n = minute.slice(2);
    return `Every ${n} minutes`;
  }

  // Every hour at a fixed minute
  if (
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*" &&
    !minute.includes("*")
  ) {
    return `Every hour at minute ${minute}`;
  }

  // Every N hours
  if (
    hour.startsWith("*/") &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    const n = hour.slice(2);
    const atMinute = minute === "0" ? "" : ` at minute ${minute}`;
    return `Every ${n} hours${atMinute}`;
  }

  // Daily at a fixed time
  if (
    !minute.includes("*") &&
    !hour.includes("*") &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return `Daily at ${cronTime(hour, minute)}`;
  }

  // Weekly on a specific day
  if (
    !minute.includes("*") &&
    !hour.includes("*") &&
    dayOfMonth === "*" &&
    month === "*" &&
    !dayOfWeek.includes("*") &&
    !dayOfWeek.includes(",") &&
    !dayOfWeek.includes("-")
  ) {
    const dayIndex = Number.parseInt(dayOfWeek, 10);
    const weekdayName =
      dayIndex >= 0 && dayIndex <= 6
        ? CRON_WEEKDAYS[dayIndex]
        : `day ${dayOfWeek}`;
    return `Every ${weekdayName} at ${cronTime(hour, minute)}`;
  }

  // Monthly on a specific day
  if (
    !minute.includes("*") &&
    !hour.includes("*") &&
    !dayOfMonth.includes("*") &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return `Monthly on day ${dayOfMonth} at ${cronTime(hour, minute)}`;
  }

  // Yearly on a specific date
  if (
    !minute.includes("*") &&
    !hour.includes("*") &&
    !dayOfMonth.includes("*") &&
    !month.includes("*") &&
    dayOfWeek === "*"
  ) {
    const monthIndex = Number.parseInt(month, 10) - 1;
    const monthName =
      monthIndex >= 0 && monthIndex <= 11
        ? CRON_MONTHS[monthIndex]
        : `month ${month}`;
    return `Yearly on ${monthName} ${dayOfMonth} at ${cronTime(hour, minute)}`;
  }

  return cron;
}
