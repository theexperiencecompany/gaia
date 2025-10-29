import { useCallback } from "react";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import { useCalendarStore } from "@/stores/calendarStore";

export const useCalendarOperations = () => {
  const {
    setEvents,
    setLoading,
    setError,
    clearError,
    selectedCalendars,
    addLoadedRange,
    isDateRangeLoaded,
    setLoadingPast,
    setLoadingFuture,
  } = useCalendarStore();

  const loadEvents = useCallback(
    async (
      calendarIds?: string[],
      reset = false,
      customStartDate?: Date,
      customEndDate?: Date,
      direction?: "past" | "future",
    ) => {
      const calendarsToUse = calendarIds || selectedCalendars;
      if (calendarsToUse.length === 0) return;

      // Format dates as YYYY-MM-DD for comparison
      const formatDateForComparison = (date: Date) =>
        date.toISOString().split("T")[0];

      // Check if this range is already loaded (only for specific ranges)
      if (
        customStartDate &&
        customEndDate &&
        !reset &&
        isDateRangeLoaded(customStartDate, customEndDate, calendarsToUse)
      ) {
        console.log(
          "Range already loaded:",
          formatDateForComparison(customStartDate),
          "to",
          formatDateForComparison(customEndDate),
        );
        return;
      }

      // Set appropriate loading state based on direction
      if (direction === "past") {
        setLoadingPast(true);
      } else if (direction === "future") {
        setLoadingFuture(true);
      } else {
        // General events loading (initial fetch)
        setLoading("events", true);
      }

      clearError("events");

      try {
        let startDate: Date;
        let endDate: Date;

        if (customStartDate && customEndDate) {
          // Use provided custom date range
          startDate = customStartDate;
          endDate = customEndDate;
        } else {
          // Use default 3-month rolling window: 1 month past to 2 months future
          const now = new Date();
          startDate = new Date(now);
          startDate.setMonth(startDate.getMonth() - 1);
          startDate.setDate(1); // Start of month

          endDate = new Date(now);
          endDate.setMonth(endDate.getMonth() + 2);
          endDate.setDate(0); // End of month
        }

        // Format dates as YYYY-MM-DD
        const formatDate = (date: Date) => date.toISOString().split("T")[0];

        const response = await calendarApi.fetchMultipleCalendarEvents(
          calendarsToUse,
          formatDate(startDate),
          formatDate(endDate),
          true, // fetch_all = true for calendar page
        );

        setEvents(response.events, reset);

        // Log if any calendars were truncated (hit safety limit)
        if (response.has_more && response.calendars_truncated?.length) {
          console.warn(
            `Some calendars hit event limits:`,
            response.calendars_truncated,
          );
        }

        // Track loaded range
        if (customStartDate && customEndDate) {
          addLoadedRange(
            formatDate(customStartDate),
            formatDate(customEndDate),
            calendarsToUse,
          );
        }

        return response;
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : "Failed to fetch events";
        setError("events", errorMessage);
        throw error;
      } finally {
        // Clear appropriate loading state
        if (direction === "past") {
          setLoadingPast(false);
        } else if (direction === "future") {
          setLoadingFuture(false);
        } else {
          setLoading("events", false);
        }
      }
    },
    [
      selectedCalendars,
      setLoading,
      setError,
      clearError,
      setEvents,
      addLoadedRange,
      isDateRangeLoaded,
      setLoadingPast,
      setLoadingFuture,
    ],
  );

  return {
    loadEvents,
  };
};
