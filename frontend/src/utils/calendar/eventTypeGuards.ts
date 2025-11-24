import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
  TimedEvent,
} from "@/types/features/calendarTypes";

export type AnyCalendarEvent =
  | CalendarEvent
  | CalendarEditOptions
  | CalendarDeleteOptions;

export const isTimedEvent = (event: CalendarEvent): event is TimedEvent =>
  "start" in event && "end" in event;

export const isAddEvent = (event: AnyCalendarEvent): event is CalendarEvent =>
  !("event_id" in event);

export const isEditEvent = (
  event: AnyCalendarEvent,
): event is CalendarEditOptions =>
  "event_id" in event && "original_summary" in event;

export const isDeleteEvent = (
  event: AnyCalendarEvent,
): event is CalendarDeleteOptions =>
  "event_id" in event && !("original_summary" in event);
