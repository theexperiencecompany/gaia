import { apiService } from "@/lib/api";
import type { CalendarEvent } from "../types/calendar-types";

export async function fetchUpcomingEvents(days = 30): Promise<CalendarEvent[]> {
  return apiService.get<CalendarEvent[]>(`/calendar/events?days=${days}`);
}
