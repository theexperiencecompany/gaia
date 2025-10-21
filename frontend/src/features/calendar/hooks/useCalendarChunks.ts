import { useCallback, useEffect, useState } from "react";

import {
  getChunkDates,
  getRequiredChunks,
} from "@/features/calendar/utils/dateRangeUtils";

interface UseCalendarChunksProps {
  extendedDates: Date[];
  selectedCalendars: string[];
  isInitialized: boolean;
  loadEvents: (
    pageToken?: string | null,
    calendarIds?: string[],
    reset?: boolean,
    customStartDate?: Date,
    customEndDate?: Date,
  ) => Promise<any>;
}

export const useCalendarChunks = ({
  extendedDates,
  selectedCalendars,
  isInitialized,
  loadEvents,
}: UseCalendarChunksProps) => {
  const [fetchedChunks, setFetchedChunks] = useState<Set<string>>(new Set());

  const fetchMissingChunks = useCallback(async () => {
    if (
      selectedCalendars.length === 0 ||
      !isInitialized ||
      extendedDates.length === 0
    ) {
      return;
    }

    const requiredChunks = getRequiredChunks(extendedDates);
    const missingChunks = requiredChunks.filter(
      (chunk) => !fetchedChunks.has(chunk),
    );

    if (missingChunks.length === 0) return;

    const fetchPromises = missingChunks.map(async (chunkKey) => {
      const { start, end } = getChunkDates(chunkKey);

      try {
        await loadEvents(null, selectedCalendars, false, start, end);
        setFetchedChunks((prev) => new Set([...prev, chunkKey]));
      } catch (error) {
        console.error(`Failed to fetch chunk ${chunkKey}:`, error);
      }
    });

    await Promise.all(fetchPromises);
  }, [
    selectedCalendars,
    isInitialized,
    extendedDates,
    fetchedChunks,
    loadEvents,
  ]);

  const resetChunks = useCallback(() => {
    setFetchedChunks(new Set());
  }, []);

  useEffect(() => {
    fetchMissingChunks();
  }, [fetchMissingChunks]);

  useEffect(() => {
    resetChunks();
    if (selectedCalendars.length > 0) {
      loadEvents(null, selectedCalendars, true);
    }
  }, [selectedCalendars, loadEvents, resetChunks]);

  return {
    fetchedChunks,
    resetChunks,
  };
};
