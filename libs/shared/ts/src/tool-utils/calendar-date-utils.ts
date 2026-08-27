/**
 * Calendar date formatting utilities — the one canonical implementation for
 * web and mobile calendar cards. Date-only strings are parsed anchored to
 * local noon so timezone offsets can't shift them across day boundaries.
 */

function parseCalendarDate(dateString: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    return new Date(`${dateString}T12:00:00`);
  }
  return new Date(dateString);
}

/** Format date with relative labels (Today, Tomorrow, Yesterday). */
export function formatDateWithRelative(dateString: string): string {
  const date = parseCalendarDate(dateString);
  if (Number.isNaN(date.getTime())) return "Date unavailable";

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const compareDate = new Date(date);
  compareDate.setHours(0, 0, 0, 0);

  const fullDate = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  if (compareDate.getTime() === today.getTime()) return `${fullDate} (Today)`;
  if (compareDate.getTime() === tomorrow.getTime())
    return `${fullDate} (Tomorrow)`;
  if (compareDate.getTime() === yesterday.getTime())
    return `${fullDate} (Yesterday)`;
  return fullDate;
}

export function formatTimeString(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const hour12 = hours % 12 || 12;
  const minuteStr = minutes.toString().padStart(2, "0");

  if (minutes === 0) {
    return `${hour12} ${ampm}`;
  }
  return `${hour12}:${minuteStr} ${ampm}`;
}

/** Format time range for display (e.g., "10 – 11 AM", "9 AM – 2 PM"). */
export function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return startTime;
  }

  const startStr = formatTimeString(start);
  const endStr = formatTimeString(end);

  if (start.getHours() < 12 && end.getHours() >= 12) {
    return `${startStr} – ${endStr}`;
  }
  if (start.getHours() >= 12 && end.getHours() >= 12) {
    return `${startStr.replace(" PM", "")} – ${endStr}`;
  }
  if (start.getHours() < 12 && start.getHours() < 12 && end.getHours() < 12) {
    return `${startStr.replace(" AM", "")} – ${endStr}`;
  }
  return `${startStr} – ${endStr}`;
}

/** Normalizes any date-ish input into a YYYY-MM-DD bucket key. */
export function bucketDate(input: string): string {
  const t = new Date(input);
  if (Number.isNaN(t.getTime())) return new Date().toISOString().slice(0, 10);
  return t.toISOString().slice(0, 10);
}

/** Check if a date string is date-only (no time). */
export function isDateOnly(dateString: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(dateString);
}

/** Format date for all-day events. */
export function formatAllDayDate(dateString: string): string {
  try {
    const date = parseCalendarDate(dateString);
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(date);
  } catch (error) {
    console.error("Error formatting all-day date:", error);
    return dateString;
  }
}

/** Format datetime for timed events. */
export function formatTimedEventDate(isoString: string): string {
  try {
    const withoutTimezone = isoString.replace(/([+-]\d{2}:\d{2})$/, "");
    const date = new Date(withoutTimezone);

    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      hour12: true,
    }).format(date);
  } catch (error) {
    console.error("Error formatting timed event date:", error);
    return isoString;
  }
}

/** Format date range for all-day events. */
export function formatAllDayDateRange(
  startDate: string,
  endDate: string,
): string {
  try {
    const start = parseCalendarDate(startDate);
    const end = parseCalendarDate(endDate);

    if (start.toDateString() === end.toDateString()) {
      return formatAllDayDate(startDate);
    }

    const startFormatted = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
    }).format(start);

    const endFormatted = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(end);

    return `${startFormatted} - ${endFormatted}`;
  } catch (error) {
    console.error("Error formatting date range:", error);
    return `${startDate} - ${endDate}`;
  }
}

/** Get event duration text. */
export function getEventDurationText(
  startDate: string,
  endDate?: string,
): string {
  if (!endDate) return "Single event";

  try {
    const start = new Date(startDate);
    const end = new Date(endDate);
    const diffMs = end.getTime() - start.getTime();
    const diffHours = diffMs / (1000 * 60 * 60);

    if (diffHours < 1) {
      const diffMinutes = Math.round(diffMs / (1000 * 60));
      return `${diffMinutes} minute${diffMinutes !== 1 ? "s" : ""}`;
    } else if (diffHours < 24) {
      const hours = Math.round(diffHours);
      return `${hours} hour${hours !== 1 ? "s" : ""}`;
    } else {
      const days = Math.round(diffHours / 24);
      return `${days} day${days !== 1 ? "s" : ""}`;
    }
  } catch {
    return "Duration unknown";
  }
}
