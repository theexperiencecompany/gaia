import type { CalendarEditOptions } from "@/types/features/calendarTypes";

import type { AnyCalendarEvent } from "./eventTypeGuards";

/**
 * Check if event has changes (for edit events)
 */
export function hasEventChanges(event: AnyCalendarEvent): boolean {
  if (!("action" in event) || event.action !== "edit") {
    return false;
  }

  const editEvent = event as CalendarEditOptions;
  return (
    editEvent.summary !== undefined ||
    editEvent.description !== undefined ||
    editEvent.start !== undefined ||
    editEvent.end !== undefined ||
    editEvent.is_all_day !== undefined
  );
}
