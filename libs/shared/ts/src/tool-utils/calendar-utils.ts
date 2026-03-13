/**
 * Shared calendar grouping utilities for tool cards.
 */

/**
 * Group an array of calendar events by their date (YYYY-MM-DD).
 *
 * Each event must have a `start_time` ISO string field. Events without a
 * valid `start_time` fall back to today's date.
 *
 * Returns a plain object whose keys are YYYY-MM-DD date strings and whose
 * values are arrays of the matching events, in insertion order.
 */
export function groupEventsByDate<T extends { start_time: string }>(
  events: T[],
): Record<string, T[]> {
  const grouped: Record<string, T[]> = {};
  for (const event of events) {
    const dateStr = event.start_time || new Date().toISOString();
    const date = new Date(dateStr).toISOString().slice(0, 10);
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(event);
  }
  return grouped;
}
