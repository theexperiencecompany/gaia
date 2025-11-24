import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

export interface CalendarEventsResponse {
  events: GoogleCalendarEvent[];
  nextPageToken: string | null;
  has_more?: boolean; // True if any calendar was truncated
  calendars_truncated?: string[]; // Calendar IDs that hit limits
  selectedCalendars?: string[]; // Calendar IDs that were queried
}

export interface CalendarItem {
  id: string;
  name: string;
  summary: string;
  primary?: boolean;
  selected?: boolean;
  backgroundColor?: string;
}
