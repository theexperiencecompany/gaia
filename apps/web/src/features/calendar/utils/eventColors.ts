import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

// Helper function to get event color dynamically
export const getEventColor = (
  event: GoogleCalendarEvent,
  calendars: CalendarItem[],
) => {
  // First priority: use calendarId if available
  if (event.calendarId) {
    const calendar = calendars.find((cal) => cal.id === event.calendarId);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Second priority: find by organizer email
  if (event.organizer?.email) {
    const calendar = calendars.find((cal) => cal.id === event.organizer?.email);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Third priority: find by creator email
  if (event.creator?.email) {
    const calendar = calendars.find((cal) => cal.id === event.creator?.email);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Fallback color
  return "#00bbff";
};
