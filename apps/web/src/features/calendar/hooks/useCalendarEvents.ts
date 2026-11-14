import { type UseQueryResult, useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

import { calendarApi } from "../api/calendarApi";
import { calendarKeys } from "../api/queryKeys";

const pad = (value: number) => String(value).padStart(2, "0");

/** Each "YYYY-MM" the dates span, oldest first. */
const monthsSpanned = (dates: readonly Date[]): string[] => [
  ...new Set(
    dates.map((date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}`),
  ),
];

const monthBounds = (month: string): { start: string; end: string } => {
  const [year, monthNumber] = month.split("-").map(Number);
  const lastDay = new Date(year, monthNumber, 0).getDate();
  return { start: `${month}-01`, end: `${month}-${pad(lastDay)}` };
};

interface CalendarEventsView {
  events: GoogleCalendarEvent[];
  isLoading: boolean;
  error: string | null;
  isLoadingFirstMonth: boolean;
  isLoadingLastMonth: boolean;
}

/** Module-level so React Query keeps the combined view's identity until a month's result changes. */
const combineMonths = (
  results: UseQueryResult<GoogleCalendarEvent[]>[],
): CalendarEventsView => {
  const byId = new Map<string, GoogleCalendarEvent>();
  for (const result of results) {
    // A multi-day event shows in every month it touches; it is one event.
    for (const event of result.data ?? []) byId.set(event.id, event);
  }
  return {
    events: [...byId.values()],
    isLoading: results.some((result) => result.isLoading),
    error: results.find((result) => result.error)?.error?.message ?? null,
    isLoadingFirstMonth: results[0]?.isLoading ?? false,
    isLoadingLastMonth: results.at(-1)?.isLoading ?? false,
  };
};

/** The selected calendars' events across every month the dates span, one cached query per month. */
export const useCalendarEvents = (
  selectedCalendars: readonly string[],
  dates: readonly Date[],
): CalendarEventsView => {
  const months = useMemo(() => monthsSpanned(dates), [dates]);
  return useQueries({
    queries: months.map((month) => ({
      queryKey: calendarKeys.monthEvents(selectedCalendars, month),
      queryFn: async (): Promise<GoogleCalendarEvent[]> => {
        const { start, end } = monthBounds(month);
        const result = await calendarApi.fetchMultipleCalendarEvents(
          [...selectedCalendars],
          start,
          end,
        );
        return result.events;
      },
      enabled: selectedCalendars.length > 0,
    })),
    combine: combineMonths,
  });
};
