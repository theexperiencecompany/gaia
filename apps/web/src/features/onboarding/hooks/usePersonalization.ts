import { useCallback, useEffect, useState } from "react";
import type { PersonalizationData } from "@/features/onboarding/types/websocket";
import { apiService } from "@/lib/api/service";

interface UsePersonalizationReturn {
  personalizationData: PersonalizationData | null;
  isLoading: boolean;
  isComplete: boolean;
  refetch: () => Promise<void>;
}

/**
 * Fetches and manages personalization data for the holo card modal.
 *
 * Data source: REST endpoint `/onboarding/personalization`. Fetched on mount
 * and re-fetched on demand via `refetch()`. There is no WebSocket push for
 * this data — the onboarding DAG pipeline writes to MongoDB and the client
 * re-reads on demand.
 */
export const usePersonalization = (
  enabled: boolean = true,
): UsePersonalizationReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasPersonalization, setHasPersonalization] = useState(false);

  const fetchPersonalization = useCallback(async () => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }

    try {
      const data = await apiService.get<PersonalizationData>(
        "/onboarding/personalization",
        { silent: true },
      );

      const isComplete =
        data.phase &&
        ["personalization_complete", "getting_started", "completed"].includes(
          data.phase,
        );

      setPersonalizationData(data);
      setHasPersonalization(!!isComplete);
      setIsLoading(false);
    } catch (error) {
      console.error("[usePersonalization] Failed to fetch:", error);
      setHasPersonalization(false);
      setIsLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    fetchPersonalization();
  }, [fetchPersonalization]);

  return {
    personalizationData,
    isLoading,
    isComplete: hasPersonalization,
    refetch: fetchPersonalization,
  };
};
