import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  isPersonalizationCompleteMessage,
  type PersonalizationData,
} from "@/features/onboarding/types/websocket";
import { apiService } from "@/lib/api";
import { wsManager } from "@/lib/websocket";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

interface UsePersonalizationReturn {
  personalizationData: PersonalizationData | null;
  isLoading: boolean;
  isComplete: boolean;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch and manage personalization data
 *
 * Data sources:
 * - Initial load: Fetches from API on mount
 * - Updates: WebSocket event when personalization completes
 * - Manual refresh: Call refetch() function
 *
 * Relies on WebSocket for real-time updates
 * and component remount for page navigation/reload.
 */
export const usePersonalization = (
  enabled: boolean = true,
): UsePersonalizationReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasPersonalization, setHasPersonalization] = useState(false);

  // Fetch personalization data from API
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

      console.log("[usePersonalization] Fetched data:", data);

      // Check if personalization is complete based on phase
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

  // Fetch on mount
  useEffect(() => {
    fetchPersonalization();
  }, [fetchPersonalization]);

  // Listen for WebSocket updates
  useEffect(() => {
    if (!enabled) return;

    const handlePersonalizationComplete = (message: unknown) => {
      if (!isPersonalizationCompleteMessage(message)) return;

      console.log("[usePersonalization] WebSocket event received");

      const data: PersonalizationData = {
        ...message.data,
        has_personalization: true,
      };

      setPersonalizationData(data);
      setHasPersonalization(true);
      setIsLoading(false);

      toast.success("Your personalized card is ready! 🎉");
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
  }, [enabled]);

  return {
    personalizationData,
    isLoading,
    isComplete: hasPersonalization,
    refetch: fetchPersonalization,
  };
};
