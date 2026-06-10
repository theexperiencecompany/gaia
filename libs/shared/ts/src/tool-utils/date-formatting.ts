/**
 * Shared date formatting utilities for tool cards.
 * Used by both web and mobile to display due dates and relative date labels.
 */

/**
 * Format a due date string into a human-readable relative label.
 *
 * Returns "Today", "Tomorrow", or "Yesterday" for those cases,
 * the weekday name for dates within the next 7 days,
 * or a short "Mon D" format for all other dates.
 */
export function formatToolDueDate(date: string): string {
  const dueDate = new Date(date);
  const now = new Date();
  // Compare on the LOCAL calendar date, not raw timestamps. Millisecond math
  // rolls the label back a day for evening times in positive-offset zones
  // (e.g. 19:06 +05:30), which is why the chat card showed "Yesterday" while
  // the todos page (which compares calendar dates) showed "Today".
  const startOfDay = (d: Date): number =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const daysDiff = Math.round(
    (startOfDay(dueDate) - startOfDay(now)) / (1000 * 60 * 60 * 24),
  );
  if (daysDiff === 0) return "Today";
  if (daysDiff === 1) return "Tomorrow";
  if (daysDiff === -1) return "Yesterday";
  if (daysDiff > 0 && daysDiff < 7) {
    return dueDate.toLocaleDateString("en-US", { weekday: "long" });
  }
  return dueDate.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}
