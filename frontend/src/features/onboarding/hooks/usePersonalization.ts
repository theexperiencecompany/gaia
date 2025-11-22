import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { apiService } from "@/lib/api";
import { wsManager } from "@/lib/websocket";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

export interface PersonalizationData {
  has_personalization?: boolean;
  phase?: string;
  house: House;
  personality_phrase: string;
  user_bio: string;
  bio_status?: "pending" | "processing" | "completed" | "no_gmail";
  account_number: number;
  member_since: string;
  name: string;
  holo_card_id: string;
  overlay_color?: string;
  overlay_opacity?: number;
  suggested_workflows: Array<{
    id: string;
    title: string;
    description: string;
    steps: Array<{ tool_category: string }>;
  }>;
}

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
        "/oauth/onboarding/personalization",
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

    const handlePersonalizationComplete = (message: any) => {
      if (message.type !== "onboarding_personalization_complete") return;

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
