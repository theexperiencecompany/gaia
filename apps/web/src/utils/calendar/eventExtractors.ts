import type { CalendarFetchData } from "@/types/features/calendarTypes";

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
