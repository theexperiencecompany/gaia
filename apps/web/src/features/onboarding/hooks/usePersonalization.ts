import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  isPersonalizationCompleteMessage,
  type PersonalizationData,
} from "@/features/onboarding/types/websocket";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { wsManager } from "@/lib/websocket/WebSocketManager";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

interface UsePersonalizationReturn {
  personalizationData: PersonalizationData | null;
  isLoading: boolean;
  isComplete: boolean;
  refetch: () => Promise<void>;
}

const fetchPersonalization = async (): Promise<PersonalizationData> => {
  return apiService.get<PersonalizationData>("/onboarding/personalization", {
    silent: true,
  });
};

/**
 * Hook to fetch and manage personalization data
 *
 * Data sources:
 * - Initial load: Fetches from API via React Query (with deduplication and caching)
 * - Updates: WebSocket event when personalization completes
 * - Manual refresh: Call refetch() function
 *
 * Relies on WebSocket for real-time updates
 * and React Query for caching and deduplication.
 */
export const usePersonalization = (
  enabled: boolean = true,
): UsePersonalizationReturn => {
  const queryClient = useQueryClient();
  const [hasPersonalization, setHasPersonalization] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["personalization"],
    queryFn: fetchPersonalization,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
  });

  // Update hasPersonalization when data changes
  useEffect(() => {
    if (!data) return;

    const isComplete =
      data.phase &&
      ["personalization_complete", "getting_started", "completed"].includes(
        data.phase,
      );
    setHasPersonalization(!!isComplete);
  }, [data]);

  // Listen for WebSocket updates
  useEffect(() => {
    if (!enabled) return;

    const handlePersonalizationComplete = (message: unknown) => {
      if (!isPersonalizationCompleteMessage(message)) return;

      const updatedData: PersonalizationData = {
        ...message.data,
        has_personalization: true,
      };

      // Update React Query cache directly with WebSocket data
      queryClient.setQueryData(["personalization"], updatedData);
      setHasPersonalization(true);

      toast.success("Your personalized card is ready! \u{1F389}");
    };

    wsManager.on(
      "onboarding_personalization_complete",
      handlePersonalizationComplete,
    );

    return () => {
      wsManager.off(
        "onboarding_personalization_complete",
        handlePersonalizationComplete,
      );
    };
  }, [enabled, queryClient]);

  return {
    personalizationData: data ?? null,
    isLoading,
    isComplete: hasPersonalization,
    refetch: async () => {
      await refetch();
    },
  };
};
