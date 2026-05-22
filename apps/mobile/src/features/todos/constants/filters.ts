import type { FilterTab, TodoCounts } from "../types/todo-types";

export interface TodoFilterDescriptor {
  key: FilterTab;
  label: string;
  countKey?: keyof TodoCounts;
}

/**
 * Filter chip strip ordering — must match the spec's design brief:
 * Today · Upcoming · Inbox · Overdue · Completed · All.
 *
 * `inbox` maps to the existing API `completed: false` filter (see
 * `useTodos.getFiltersForTab`). `overdue` is a virtual client-side
 * derivation over the `all` dataset for now (server-side filter to be
 * added in Pass 3); we keep it in the chip strip so the UX stays stable.
 */
export const TODO_FILTER_DESCRIPTORS: readonly TodoFilterDescriptor[] = [
  { key: "today", label: "Today", countKey: "today" },
  { key: "upcoming", label: "Upcoming", countKey: "upcoming" },
  { key: "inbox", label: "Inbox", countKey: "inbox" },
  { key: "overdue", label: "Overdue", countKey: "overdue" },
  { key: "completed", label: "Completed", countKey: "completed" },
  { key: "all", label: "All" },
] as const;
