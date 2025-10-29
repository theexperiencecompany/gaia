import { useQuery, UseQueryOptions } from "@tanstack/react-query";

import { apiService } from "@/lib/api";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface CalendarEventsResponse {
  events: GoogleCalendarEvent[];
  nextPageToken?: string;
}

/**
 * React Query hook for fetching upcoming calendar events with 5-minute caching
 */
export const useUpcomingEventsQuery = (
  maxResults: number = 10,
  options?: Partial<UseQueryOptions<GoogleCalendarEvent[], Error>>,
) => {
  // Calculate start_date (today) and end_date (today + 7 days) in YYYY-MM-DD
  const today = new Date();
  const startDate = today.toISOString().slice(0, 10); // YYYY-MM-DD
  const endDateObj = new Date(today);
  endDateObj.setDate(today.getDate() + 30);
  const endDate = endDateObj.toISOString().slice(0, 10);

  return useQuery({
    queryKey: ["upcoming-events", maxResults, startDate, endDate],
    queryFn: async (): Promise<GoogleCalendarEvent[]> => {
      const response = await apiService.get<CalendarEventsResponse>(
        `/calendar/events?max_results=${maxResults}&start_date=${startDate}&end_date=${endDate}`,
        {
          errorMessage: "Failed to fetch calendar events",
          silent: true,
        },
      );
      return response.events || [];
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - data stays fresh
    gcTime: 10 * 60 * 1000, // 10 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false, // Don't refetch on window focus for dashboard
    ...options,
  });
};
