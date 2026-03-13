import { useQuery } from "@tanstack/react-query";
import { fetchUpcomingEvents } from "../api/calendar-api";
import type { CalendarEvent } from "../types/calendar-types";

export function useUpcomingEvents(days = 30) {
  return useQuery<CalendarEvent[]>({
    queryKey: ["calendar", "upcoming"],
    queryFn: () => fetchUpcomingEvents(days),
    staleTime: 60_000,
  });
}
