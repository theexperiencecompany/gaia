import {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";
import { AnyCalendarEvent } from "./eventTypeGuards";

export type EventAction = "add" | "edit" | "delete";

/**
 * Infer the action type from event data
 */
export function getEventAction(event: AnyCalendarEvent): EventAction {
  if ("action" in event) {
    return event.action as EventAction;
  }
  return "add";
}

/**
 * Get event color from event data
 */
export function getEventColor(event: AnyCalendarEvent): string {
  if ("background_color" in event && event.background_color) {
    return event.background_color;
  }
  return "#00bbff"; // Default color
}

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
