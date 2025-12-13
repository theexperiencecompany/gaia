import { useCallback, useState } from "react";

import { useCalendarStore } from "@/stores/calendarStore";

import {
  generateMonthDates,
  getNextMonthRange,
  getPreviousMonthRange,
} from "../utils/dateRangeUtils";
import { useCalendarOperations } from "./useCalendarOperations";

// Load entire months instead of fixed day chunks
interface UseInfiniteCalendarLoaderProps {
  selectedCalendars: string[];
  isInitialized: boolean;
}

export const useInfiniteCalendarLoader = ({
  selectedCalendars,
  isInitialized,
}: UseInfiniteCalendarLoaderProps) => {
  const { loadEvents } = useCalendarOperations();
  const [isLoadingPast, setIsLoadingPast] = useState(false);
  const [isLoadingFuture, setIsLoadingFuture] = useState(false);

  // Use individual selectors for stable references
  const isDateRangeLoaded = useCalendarStore(
    (state) => state.isDateRangeLoaded,
  );
  const addLoadedRange = useCalendarStore((state) => state.addLoadedRange);

  const loadEventsPast = useCallback(
    async (referenceDate: Date, calendars: string[]) => {
      const formatDate = (date: Date) => date.toISOString().split("T")[0];

      // Get the previous month's range
      const { start, end } = getPreviousMonthRange(referenceDate);

      await loadEvents(calendars, false, start, end, "past");

      addLoadedRange(formatDate(start), formatDate(end), calendars);
    },
    [loadEvents, addLoadedRange],
  );

  const loadEventsFuture = useCallback(
    async (referenceDate: Date, calendars: string[]) => {
      const formatDate = (date: Date) => date.toISOString().split("T")[0];

      // Get the next month's range
      const { start, end } = getNextMonthRange(referenceDate);

      await loadEvents(calendars, false, start, end, "future");

      addLoadedRange(formatDate(start), formatDate(end), calendars);
    },
    [loadEvents, addLoadedRange],
  );

  const loadMorePast = useCallback(
    async (referenceDate: Date) => {
      if (isLoadingPast || !isInitialized || selectedCalendars.length === 0) {
        return [];
      }

      setIsLoadingPast(true);

      try {
        // Get previous month's range
        const { start, end } = getPreviousMonthRange(referenceDate);

        // Check if already loaded
        if (isDateRangeLoaded(start, end, selectedCalendars)) {
          return [];
        }

        await loadEventsPast(referenceDate, selectedCalendars);

        // Return all dates for the previous month
        return generateMonthDates(start);
      } catch (error) {
        console.error("Failed to load past events:", error);
        return [];
      } finally {
        setIsLoadingPast(false);
      }
    },
    [
      isLoadingPast,
      isInitialized,
      selectedCalendars,
      isDateRangeLoaded,
      loadEventsPast,
    ],
  );

  const loadMoreFuture = useCallback(
    async (referenceDate: Date) => {
      if (isLoadingFuture || !isInitialized || selectedCalendars.length === 0) {
        return [];
      }

      setIsLoadingFuture(true);

      try {
        // Get next month's range
        const { start, end } = getNextMonthRange(referenceDate);

        // Check if already loaded
        if (isDateRangeLoaded(start, end, selectedCalendars)) {
          return [];
        }

        await loadEventsFuture(referenceDate, selectedCalendars);

        // Return all dates for the next month
        return generateMonthDates(start);
      } catch (error) {
        console.error("Failed to load future events:", error);
        return [];
      } finally {
        setIsLoadingFuture(false);
      }
    },
    [
      isLoadingFuture,
      isInitialized,
      selectedCalendars,
      isDateRangeLoaded,
      loadEventsFuture,
    ],
  );

  return {
    loadMorePast,
    loadMoreFuture,
    isLoadingPast,
    isLoadingFuture,
  };
};
