import { useQuery, UseQueryOptions } from "@tanstack/react-query";

import { CalendarItem } from "@/types/api/calendarApiTypes";

import { calendarApi } from "../api/calendarApi";

/**
 * React Query hook for fetching calendar list with caching
 *
 * This is the centralized hook for fetching calendars. Use this in:
 * - useSharedCalendar (for calendar page and components)
 * - GridSection (with enabled flag based on integration status)
 *
 * DO NOT call this hook multiple times in the same component tree.
 * Instead, pass calendars as props from parent components that already fetch them.
 *
 * React Query will automatically cache and deduplicate requests across all consumers.
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
