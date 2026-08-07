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
