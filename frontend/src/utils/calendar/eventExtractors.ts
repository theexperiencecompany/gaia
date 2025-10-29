import {
  CalendarEventDateTime,
  CalendarFetchData,
  SameDayEvent,
} from "@/types/features/calendarTypes";

import {
  AnyCalendarEvent,
  isAddEvent,
  isDeleteEvent,
  isEditEvent,
  isTimedEvent,
} from "./eventTypeGuards";

export const extractDateFromDateTime = (
  dateTime?: CalendarEventDateTime,
): string => {
  if (!dateTime) return new Date().toISOString().slice(0, 10);
  if (dateTime.date) return dateTime.date;
  if (dateTime.dateTime)
    return new Date(dateTime.dateTime).toISOString().slice(0, 10);
  return new Date().toISOString().slice(0, 10);
};

export const extractTimestampFromDateTime = (
  dateTime?: CalendarEventDateTime,
): number => {
  if (!dateTime) return 0;
  if (dateTime.dateTime) return new Date(dateTime.dateTime).getTime();
  if (dateTime.date) return new Date(dateTime.date).getTime();
  return 0;
};

export const getEventDate = (event: AnyCalendarEvent): string => {
  if (isAddEvent(event)) {
    if (isTimedEvent(event)) {
      if (event.start.includes("T")) {
        return new Date(event.start).toISOString().slice(0, 10);
      }
      return event.start;
    }
    return new Date().toISOString().slice(0, 10);
  }

  if (isEditEvent(event)) {
    return extractDateFromDateTime(event.original_start);
  }

  if (isDeleteEvent(event)) {
    return extractDateFromDateTime(event.start);
  }

  return new Date().toISOString().slice(0, 10);
};

export const getEventTimestamp = (event: AnyCalendarEvent): number => {
  if (isAddEvent(event)) {
    if (isTimedEvent(event)) {
      return new Date(event.start).getTime();
    }
    return 0;
  }

  if (isEditEvent(event)) {
    return extractTimestampFromDateTime(event.original_start);
  }

  if (isDeleteEvent(event)) {
    return extractTimestampFromDateTime(event.start);
  }

  return 0;
};

export const getEventKey = (
  event: AnyCalendarEvent,
  index: number,
): string | number => {
  if (isAddEvent(event)) return index;
  return event.event_id || index;
};

export const extractDateFromFetchData = (event: CalendarFetchData): string => {
  if (event.start_time.includes("T")) {
    return new Date(event.start_time).toISOString().slice(0, 10);
  }
  return event.start_time;
};

export const extractTimestampFromFetchData = (
  event: CalendarFetchData,
): number => {
  return new Date(event.start_time).getTime();
};

export const getDateFromSameDayEvent = (event: SameDayEvent): string => {
  if (event.start?.dateTime) {
    return new Date(event.start.dateTime).toISOString().slice(0, 10);
  }
  if (event.start?.date) {
    return event.start.date;
  }
  return new Date().toISOString().slice(0, 10);
};

export const getTimestampFromSameDayEvent = (event: SameDayEvent): number => {
  if (event.start?.dateTime) {
    return new Date(event.start.dateTime).getTime();
  }
  if (event.start?.date) {
    return new Date(event.start.date).getTime();
  }
  return 0;
};
