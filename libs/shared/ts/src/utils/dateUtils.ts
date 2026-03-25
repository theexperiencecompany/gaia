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

function formatTime(hour: string, minute: string): string {
  const h = Number.parseInt(hour, 10);
  const m = Number.parseInt(minute, 10);
  const period = h >= 12 ? "PM" : "AM";
  const displayHour = h % 12 === 0 ? 12 : h % 12;
  const displayMinute = m === 0 ? "" : `:${String(m).padStart(2, "0")}`;
  return `${displayHour}${displayMinute} ${period}`;
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
    return `Daily at ${formatTime(hour, minute)}`;
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
    const dayName =
      dayIndex >= 0 && dayIndex <= 6
        ? CRON_WEEKDAYS[dayIndex]
        : `day ${dayOfWeek}`;
    return `Every ${dayName} at ${formatTime(hour, minute)}`;
  }

  // Monthly on a specific day
  if (
    !minute.includes("*") &&
    !hour.includes("*") &&
    !dayOfMonth.includes("*") &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return `Monthly on day ${dayOfMonth} at ${formatTime(hour, minute)}`;
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
    return `Yearly on ${monthName} ${dayOfMonth} at ${formatTime(hour, minute)}`;
  }

  return cron;
}
