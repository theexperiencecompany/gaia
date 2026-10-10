import type { CalendarFetchData } from "@/types/features/calendarTypes";

import {
  extractDateFromFetchData,
  extractTimestampFromFetchData,
} from "./eventExtractors";

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
