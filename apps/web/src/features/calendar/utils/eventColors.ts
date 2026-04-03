import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

// Helper function to get event color dynamically
export const getEventColor = (
  event: GoogleCalendarEvent,
  calendars: CalendarItem[],
) => {
  // Build index map for O(1) lookups instead of repeated .find()
  const calendarById = new Map(calendars.map((cal) => [cal.id, cal]));

  // First priority: use calendarId if available
  if (event.calendarId) {
    const calendar = calendarById.get(event.calendarId);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Second priority: find by organizer email
  if (event.organizer?.email) {
    const calendar = calendarById.get(event.organizer.email);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Third priority: find by creator email
  if (event.creator?.email) {
    const calendar = calendarById.get(event.creator.email);
    if (calendar?.backgroundColor) return calendar.backgroundColor;
  }

  // Fallback color
  return "#00bbff";
};
