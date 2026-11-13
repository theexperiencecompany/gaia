import type { CalendarEventsResponse } from "@shared/api/generated";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

/** `CalendarEventsResult` with the passthrough events narrowed to Google's event shape. */
export type CalendarEventsResult = Omit<CalendarEventsResponse, "events"> & {
  events: GoogleCalendarEvent[];
};

export interface CalendarItem {
  id: string;
  name: string;
  summary: string;
  primary?: boolean;
  selected?: boolean;
  backgroundColor?: string;
}
