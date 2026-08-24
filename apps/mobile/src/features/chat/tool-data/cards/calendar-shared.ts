// -- Shared date/time helpers for the calendar tool cards ---------------------
// Mirrors web utils/date/calendarDateUtils.ts. Extracted from
// calendar-fetch / calendar-edit / calendar-delete / calendar-options cards,
// which each carried their own copy.

/**
 * Date-only strings (YYYY-MM-DD) are parsed anchored to local noon so timezone
 * offsets can't shift them to the previous/next day before comparison.
 */
function parseCalendarDate(dateString: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    return new Date(`${dateString}T12:00:00`);
  }
  return new Date(dateString);
}

export function formatDateWithRelative(dateString: string): string {
  const date = parseCalendarDate(dateString);
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
  if (start.getHours() < 12 && end.getHours() < 12) {
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
