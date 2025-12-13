import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { useCalendarStore } from "@/stores/calendarStore";

import { calendarApi } from "../api/calendarApi";

/**
 * React Query hook for fetching and syncing calendar preferences from backend
 *
 * This hook fetches the user's selected calendar IDs from the backend and
 * automatically syncs them to the Zustand store when they change.
 *
 * Use this in components that need to initialize calendar preferences from the server,
 * particularly after OAuth connection.
 */
export const useCalendarPreferences = (
  options?: Partial<UseQueryOptions<string[], Error>>,
) => {
  const setSelectedCalendars = useCalendarStore(
    (state) => state.setSelectedCalendars,
  );

  const query = useQuery({
    queryKey: ["calendarPreferences"],
    queryFn: async (): Promise<string[]> => {
      return await calendarApi.fetchCalendarPreferences();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
    retry: 1,
    refetchOnWindowFocus: false,
    ...options,
  });

  // Sync backend preferences to store when data is fetched
  // This will override any localStorage values to ensure backend is source of truth
  useEffect(() => {
    if (query.isFetched) {
      const currentStore = useCalendarStore.getState().selectedCalendars;

      if (query.data && query.data.length > 0) {
        console.log(
          "[Calendar Preferences] Backend returned:",
          query.data.length,
          "calendars",
        );
        console.log(
          "[Calendar Preferences] Current store has:",
          currentStore.length,
          "calendars",
        );

        // Always sync from backend when available
        if (JSON.stringify(currentStore) !== JSON.stringify(query.data)) {
          console.log("[Calendar Preferences] Syncing to store...");
          setSelectedCalendars(query.data);
        } else {
          console.log("[Calendar Preferences] Already in sync");
        }
      } else if (query.data && query.data.length === 0) {
        console.warn(
          "[Calendar Preferences] Backend returned empty preferences",
        );
      }
    }
  }, [query.isFetched, query.data, setSelectedCalendars]);

  return query;
};
