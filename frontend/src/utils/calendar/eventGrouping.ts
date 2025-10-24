import { CalendarFetchData } from "@/types/features/calendarTypes";

import {
  extractDateFromFetchData,
  extractTimestampFromFetchData,
  getEventDate,
  getEventKey,
  getEventTimestamp,
} from "./eventExtractors";
import { AnyCalendarEvent } from "./eventTypeGuards";

export interface GroupedEvent<T> {
  event: T;
  key: string | number;
}

export const groupEventsByDate = <T extends AnyCalendarEvent>(
  events: T[],
): Record<string, GroupedEvent<T>[]> => {
  const grouped: Record<string, GroupedEvent<T>[]> = {};

  events.forEach((event, index) => {
    const eventDate = getEventDate(event);

    if (!grouped[eventDate]) {
      grouped[eventDate] = [];
    }

    const key = getEventKey(event, index);
    grouped[eventDate].push({ event, key });
  });

  Object.values(grouped).forEach((dayEvents) =>
    dayEvents.sort((a, b) => {
      const aTime = getEventTimestamp(a.event);
      const bTime = getEventTimestamp(b.event);
      return aTime - bTime;
    }),
  );

  return grouped;
};

export const groupFetchDataByDate = (
  events: CalendarFetchData[],
): Record<string, CalendarFetchData[]> => {
  const grouped: Record<string, CalendarFetchData[]> = {};

  events.forEach((event) => {
    const eventDate = extractDateFromFetchData(event);

    if (!grouped[eventDate]) {
      grouped[eventDate] = [];
    }
    grouped[eventDate].push(event);
  });

  Object.values(grouped).forEach((dayEvents) =>
    dayEvents.sort((a, b) => {
      const aTime = extractTimestampFromFetchData(a);
      const bTime = extractTimestampFromFetchData(b);
      return aTime - bTime;
    }),
  );

  return grouped;
};
