"use client";

import { useCallback } from "react";

import { useCalendarStore } from "@/stores/calendarStore";

import { useCalendarOperations } from "./useCalendarOperations";
import { useCalendarsQuery } from "./useCalendarsQuery";

export const useSharedCalendar = () => {
  const {
    selectedCalendars,
    events,
    nextPageToken,
    loading,
    error,
    setSelectedCalendars,
    toggleCalendarSelection,
    resetEvents,
    clearError,
  } = useCalendarStore();

  const { loadEvents } = useCalendarOperations();

  // Use React Query for calendars with caching
  const calendarsQuery = useCalendarsQuery();
  const calendars = calendarsQuery.data ?? [];
  const isInitialized = calendarsQuery.isFetched;

  // Handle calendar selection
  const handleCalendarSelect = useCallback(
    (calendarId: string) => {
      toggleCalendarSelection(calendarId);
    },
    [toggleCalendarSelection],
  );

  // Clear events
  const clearEvents = useCallback(() => {
    resetEvents();
  }, [resetEvents]);

  return {
    // State
    calendars,
    selectedCalendars,
    events,
    nextPageToken,
    loading: {
      ...loading,
      calendars: calendarsQuery.isLoading,
    },
    error: {
      ...error,
      calendars: calendarsQuery.error?.message ?? null,
    },
    isInitialized,

    // Actions
    loadEvents,
    clearEvents,
    handleCalendarSelect,
    setSelectedCalendars,
    clearError,
    refetchCalendars: calendarsQuery.refetch,
  };
};
