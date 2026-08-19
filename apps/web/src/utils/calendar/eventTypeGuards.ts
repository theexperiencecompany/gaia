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
