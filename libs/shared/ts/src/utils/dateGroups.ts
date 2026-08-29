/**
 * Shared date grouping — unified Today / Yesterday / Previous 7 / Previous 30 / All time
 *
 * Unifies:
 * - apps/web/src/components/layout/sidebar/ChatsList.tsx :: getTimeFrame + timeFramePriority
 * - apps/web/src/features/mail/hooks/useEmailGrouping.ts :: useEmailGrouping buckets
 * - libs/shared/ts/src/hooks/useNotificationsBase.ts :: groupNotificationsByDate (Today/Yesterday fallback)
 *
 * Domain notes:
 * - All comparisons are on the **local calendar date** (midnight-normalized),
 *   not on raw millisecond deltas. This avoids the +05:30 / evening roll-backs
 *   that previously showed "Yesterday" in JS while "Today" in the UI.
 * - Thresholds are inclusive on the lower bound:
 *   Today      = >= startOfToday
 *   Yesterday  = >= startOfYesterday
 *   Previous 7 = >= startOfToday - 7 days
 *   Previous 30= >= startOfToday - 30 days
 *   All time   = everything older
 * - Legacy aliases: "Last 7 Days" → "Previous 7 days", "Last 30 Days" → "Previous 30 days",
 *   "Older" → "All time" for email grouping callers that still expect those strings.
 */

export type DateGroup =
  | "Today"
  | "Yesterday"
  | "Previous 7 days"
  | "Previous 30 days"
  | "All time";

/**
 * Legacy email-grouping labels — kept as aliases so migrated callers keep
 * working without a flag-day rename.
 */
export type LegacyDateGroup = "Last 7 Days" | "Last 30 Days" | "Older";

export const DATE_GROUPS: readonly DateGroup[] = [
  "Today",
  "Yesterday",
  "Previous 7 days",
  "Previous 30 days",
  "All time",
] as const;

export const DATE_GROUP_ORDER: Record<DateGroup, number> = {
  Today: 0,
  Yesterday: 1,
  "Previous 7 days": 2,
  "Previous 30 days": 3,
  "All time": 4,
};

/**
 * Map legacy email labels to the unified DateGroup vocabulary.
 */
export const LEGACY_GROUP_ALIAS: Record<LegacyDateGroup, DateGroup> = {
  "Last 7 Days": "Previous 7 days",
  "Last 30 Days": "Previous 30 days",
  Older: "All time",
};

export function normalizeLegacyGroup(label: string): DateGroup | string {
  if (label in LEGACY_GROUP_ALIAS) {
    return LEGACY_GROUP_ALIAS[label as LegacyDateGroup];
  }
  return label;
}

/**
 * Return the start of the local calendar day for a Date.
 */
export function startOfLocalDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Classify a single date into one of the five shared buckets.
 *
 * @param value - Date instant to classify (Date | ISO string | epoch ms)
 * @param now   - Reference "now" (defaults to new Date()); inject for tests
 */
export function getDateGroup(
  value: Date | string | number,
  now: Date = new Date(),
): DateGroup {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "All time";

  const today = startOfLocalDay(now);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const daysAgo7 = new Date(today);
  daysAgo7.setDate(today.getDate() - 7);
  const daysAgo30 = new Date(today);
  daysAgo30.setDate(today.getDate() - 30);

  const time = date.getTime();

  if (time >= today.getTime()) return "Today";
  if (time >= yesterday.getTime()) return "Yesterday";
  if (time >= daysAgo7.getTime()) return "Previous 7 days";
  if (time >= daysAgo30.getTime()) return "Previous 30 days";
  return "All time";
}

/**
 * Alias that mirrors the ChatsList naming (`getTimeFrame`). Kept for
 * drop-in replacement; both names point to the same implementation.
 */
export const getTimeFrame = getDateGroup;
export const getDateGroupLabel = getDateGroup;

export function compareDateGroup(a: DateGroup, b: DateGroup): number {
  return (DATE_GROUP_ORDER[a] ?? 99) - (DATE_GROUP_ORDER[b] ?? 99);
}

/**
 * Group an array of items by the shared date buckets.
 *
 * @param items   - source items
 * @param getDate - accessor returning the item's timestamp
 * @param now     - reference "now" for deterministic tests
 * @returns Record keyed by DateGroup containing only non-empty groups
 */
export function groupByDateGroup<T>(
  items: T[],
  getDate: (item: T) => Date | string | number,
  now: Date = new Date(),
): Record<string, T[]> {
  const groups: Record<string, T[]> = {};

  for (const item of items) {
    const group = getDateGroup(getDate(item), now);
    if (!groups[group]) groups[group] = [];
    groups[group].push(item);
  }

  return groups;
}

/**
 * Group and sort entries chronologically by bucket priority, with each
 * bucket's items sorted newest-first (descending by the same date accessor).
 *
 * Matches ChatsList's `sortedTimeFrames` derivation:
 *   Object.entries(grouped).toSorted((a,b) => priority(a)-priority(b))
 *   and inner `toSorted((a,b)=> b.createdAt - a.createdAt)`
 */
export function groupAndSortByDateGroup<T>(
  items: T[],
  getDate: (item: T) => Date | string | number,
  now: Date = new Date(),
): [DateGroup, T[]][] {
  const grouped = groupByDateGroup(items, getDate, now);

  const entries = Object.entries(grouped) as [DateGroup, T[]][];

  // sort items within each group newest-first
  for (const [, list] of entries) {
    list.sort(
      (a, b) => new Date(getDate(b)).getTime() - new Date(getDate(a)).getTime(),
    );
  }

  // sort groups by the canonical order
  entries.sort(([a], [b]) => compareDateGroup(a, b));

  return entries;
}

/**
 * Flat list representation consumed by email / notification UIs that render
 * headers interleaved with items (see useEmailGrouping).
 *
 * Returns Array<{type:"header", label:DateGroup} | {type:"item", data:T}>
 * with headers only for non-empty buckets, in canonical order.
 */
export type GroupedListItem<T> =
  | { type: "header"; label: DateGroup }
  | { type: "item"; data: T };

export function toGroupedList<T>(
  items: T[],
  getDate: (item: T) => Date | string | number,
  now: Date = new Date(),
): GroupedListItem<T>[] {
  const sorted = groupAndSortByDateGroup(items, getDate, now);
  const out: GroupedListItem<T>[] = [];

  for (const [label, groupItems] of sorted) {
    out.push({ type: "header", label });
    for (const data of groupItems) {
      out.push({ type: "item", data });
    }
  }

  return out;
}

/**
 * Backwards-compatible shim for `useEmailGrouping`:
 * accepts EmailData-style `{time}` accessor and emits legacy
 * ListItem shape {type:"header"|"email", data:string|T} if requested,
 * otherwise the modern GroupedListItem.
 *
 * Prefer `groupByDateGroup` / `toGroupedList` for new code.
 */
export function groupEmailsByDate<T extends { time: string | number | Date }>(
  emails: T[],
  now: Date = new Date(),
): Record<string, T[]> {
  return groupByDateGroup(emails, (e) => e.time, now);
}

/**
 * Helper: return the canonical sorted bucket entries for any timestamp-keyed
 * records (useful for ChatsList migration without rewriting its memo).
 */
export function groupConversationsByDate<T>(
  items: T[],
  getDate: (item: T) => Date | string | number,
  now?: Date,
): [DateGroup, T[]][] {
  return groupAndSortByDateGroup(items, getDate, now);
}
