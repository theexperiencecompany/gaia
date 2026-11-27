import type {
  CalendarEventsResponse,
  GoogleCalendarListEntry,
} from "@shared/api/generated";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

/** `CalendarEventsResult` with the passthrough events narrowed to Google's event shape. */
export type CalendarEventsResult = Omit<CalendarEventsResponse, "events"> & {
  events: GoogleCalendarEvent[];
};

export type CalendarItem = GoogleCalendarListEntry;
