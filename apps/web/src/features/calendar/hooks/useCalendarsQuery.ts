import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { CalendarItem } from "@/types/api/calendarApiTypes";

import { calendarApi } from "../api/calendarApi";

/**
 * Centralized hook for fetching the calendar list (used by
 * useSharedCalendar, GridSection) — React Query caches and dedupes it
 * across all consumers.
 *
 * Do not call this multiple times in one component tree; pass calendars as
 * props from a parent that already fetches them.
 */
export const useCalendarsQuery = (
  options?: Partial<UseQueryOptions<CalendarItem[], Error>>,
) => {
  return useQuery({
    queryKey: ["calendars"],
    queryFn: async (): Promise<CalendarItem[]> => {
      return await calendarApi.fetchCalendars();
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - calendars don't change often
    gcTime: 30 * 60 * 1000, // 30 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
