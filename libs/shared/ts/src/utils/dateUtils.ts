const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

function toDate(date: string | Date): Date {
  return date instanceof Date ? date : new Date(date);
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

/**
 * Format a date as a human-readable string.
 * Supported formats: "short" (Jan 5), "long" (January 5, 2025), "datetime" (Jan 5, 2025, 3:00 PM).
 * Defaults to "short".
 */
export function formatDate(
  date: string | Date,
  format: "short" | "long" | "datetime" = "short",
): string {
  const d = toDate(date);

  switch (format) {
    case "long":
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    case "datetime":
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    default:
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
  }
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
  const d = toDate(date);

  switch (format) {
    case "weekday":
      return d.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
    case "month":
      return d.toLocaleDateString(undefined, {
        month: "short",
        timeZone: "UTC",
      });
    default:
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
  }
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
  const now = new Date();

  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );
  const startOfDue = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round(
    (startOfDue.getTime() - startOfToday.getTime()) / DAY_MS,
  );

  if (diffDays < 0) {
    return `Overdue · ${formatDate(d, "short")}`;
  }
  if (diffDays === 0) return "Due today";
  if (diffDays === 1) return "Due tomorrow";
  if (diffDays < 7) {
    return `Due ${d.toLocaleDateString(undefined, { weekday: "long" })}`;
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

  const now = new Date();
  const startOfNow = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const startOfDue = new Date(
    due.getFullYear(),
    due.getMonth(),
    due.getDate(),
  ).getTime();

  const diffDays = Math.round((startOfDue - startOfNow) / DAY_MS);

  if (diffDays < 0) return "overdue";
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "tomorrow";
  if (diffDays <= 3) return "soon";
  return "later";
}

/**
 * Mirror of web's `parseDate` (apps/web/src/utils/date/dateUtils.ts):
 * - Short relative time for differences under 7 days (e.g. "3 mins ago",
 *   "1 hour ago", "2 days ago", or "just now").
 * - Full date with day suffix and time for older entries
 *   (e.g. "13th Apr '25 (3:45 PM)").
 *
 * Returns an empty string for invalid input.
 */
export function parseRelativeDateLabel(value: string | Date): string {
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  const formattedTime = date
    .toLocaleString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .toUpperCase();

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

  const month = date.toLocaleString(undefined, { month: "short" });
  const year = date.toLocaleString(undefined, { year: "2-digit" });
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
