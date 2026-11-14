"use client";

import { useCallback } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import {
  useCalendarPreferences,
  useUpdateCalendarPreferences,
} from "./useCalendarPreferences";
import { useCalendarsQuery } from "./useCalendarsQuery";

const NO_CALENDARS: string[] = [];

/** The user's calendars and their selection, both read from the server. */
export const useSharedCalendar = () => {
  const { getIntegrationStatus } = useIntegrations();
  const isCalendarConnected =
    getIntegrationStatus("googlecalendar")?.connected || false;

  const preferencesQuery = useCalendarPreferences({
    enabled: isCalendarConnected,
  });
  const calendarsQuery = useCalendarsQuery({ enabled: isCalendarConnected });
  const { mutate: saveSelection } = useUpdateCalendarPreferences();

  const calendars = calendarsQuery.data ?? [];
  const selectedCalendars = preferencesQuery.data ?? NO_CALENDARS;

  const handleCalendarSelect = useCallback(
    (calendarId: string) => {
      saveSelection(
        selectedCalendars.includes(calendarId)
          ? selectedCalendars.filter((id) => id !== calendarId)
          : [...selectedCalendars, calendarId],
      );
    },
    [saveSelection, selectedCalendars],
  );

  return {
    calendars,
    selectedCalendars,
    isInitialized: calendarsQuery.isFetched && preferencesQuery.isFetched,
    isLoadingCalendars: calendarsQuery.isLoading,
    calendarsError: calendarsQuery.error?.message ?? null,
    handleCalendarSelect,
  };
};
