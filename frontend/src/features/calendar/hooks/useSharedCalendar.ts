"use client";

import { useCallback, useMemo } from "react";

import { useCalendarStore } from "@/stores/calendarStore";

import { useCalendarOperations } from "./useCalendarOperations";
import { useCalendarsQuery } from "./useCalendarsQuery";

export const useSharedCalendar = () => {
  // Use individual selectors to prevent unnecessary re-renders
  const selectedCalendars = useCalendarStore(
    (state) => state.selectedCalendars,
  );
  const events = useCalendarStore((state) => state.events);
  const loading = useCalendarStore((state) => state.loading);
  const error = useCalendarStore((state) => state.error);
  const setSelectedCalendars = useCalendarStore(
    (state) => state.setSelectedCalendars,
  );
  const toggleCalendarSelection = useCalendarStore(
    (state) => state.toggleCalendarSelection,
  );
  const resetEvents = useCalendarStore((state) => state.resetEvents);
  const clearError = useCalendarStore((state) => state.clearError);

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

  // Memoize loading object to prevent new references
  const loadingState = useMemo(
    () => ({
      ...loading,
      calendars: calendarsQuery.isLoading,
    }),
    [loading, calendarsQuery.isLoading],
  );

  // Memoize error object to prevent new references
  const errorState = useMemo(
    () => ({
      ...error,
      calendars: calendarsQuery.error?.message ?? null,
    }),
    [error, calendarsQuery.error],
  );

  return {
    // State
    calendars,
    selectedCalendars,
    events,
    loading: loadingState,
    error: errorState,
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
