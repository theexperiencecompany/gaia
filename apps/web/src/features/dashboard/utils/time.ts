/** "2:00 PM" from an ISO datetime; empty string for date-only values. */
export function formatClockTime(iso: string | null): string {
  if (!iso || !iso.includes("T")) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "Thu, Jul 10" from a YYYY-MM-DD date string (local, no TZ shift). */
export function formatShortDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (!year || !month || !day) return dateStr;
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}
