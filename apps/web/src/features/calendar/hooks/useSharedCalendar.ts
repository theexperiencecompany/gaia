"use client";

import { useCallback, useMemo } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useCalendarStore } from "@/stores/calendarStore";

import { calendarApi } from "../api/calendarApi";
import { useCalendarOperations } from "./useCalendarOperations";
import { useCalendarPreferences } from "./useCalendarPreferences";
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
  const { getIntegrationStatus } = useIntegrations();

  // Check if calendar integration is connected
  const calendarStatus = getIntegrationStatus("googlecalendar");
  const isCalendarConnected = calendarStatus?.connected || false;

  // Fetch calendar preferences from backend (syncs to store automatically)
  const preferencesQuery = useCalendarPreferences({
    enabled: isCalendarConnected,
  });

  // Use React Query for calendars with caching - only fetch if connected
  const calendarsQuery = useCalendarsQuery({
    enabled: isCalendarConnected,
  });
  const calendars = calendarsQuery.data ?? [];
  const isInitialized = calendarsQuery.isFetched && preferencesQuery.isFetched;

  // Handle calendar selection
  const handleCalendarSelect = useCallback(
    async (calendarId: string) => {
      // Toggle in store (updates UI immediately)
      toggleCalendarSelection(calendarId);

      // Get updated selections after toggle
      const updatedSelections = useCalendarStore.getState().selectedCalendars;

      // Sync to backend
      try {
        await calendarApi.updateCalendarPreferences(updatedSelections);
        console.log(
          "[Calendar] Synced selection to backend:",
          updatedSelections.length,
          "calendars",
        );
      } catch (error) {
        console.error("[Calendar] Failed to sync selection to backend:", error);
      }
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
