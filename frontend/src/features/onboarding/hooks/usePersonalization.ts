import { useCallback,useEffect, useState } from "react";
import { toast } from "sonner";

import { apiService } from "@/lib/api";
import { wsManager } from "@/lib/websocket";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

export interface PersonalizationData {
  has_personalization?: boolean;
  house: House;
  personality_phrase: string;
  user_bio: string;
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

export const usePersonalization = (
  enabled: boolean = true,
): UsePersonalizationReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Fetch personalization data from API
  const fetchPersonalization = useCallback(async () => {
    if (!enabled) return;

    try {
      const data = await apiService.get<PersonalizationData>(
        "/oauth/onboarding/personalization",
        { silent: true },
      );

      // Only set if personalization is complete
      if (data.has_personalization) {
        setPersonalizationData(data);
        setIsLoading(false);
      } else {
        setIsLoading(true);
      }
    } catch (error) {
      console.error("Failed to fetch personalization:", error);
      setIsLoading(true);
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
      if (message.type === "onboarding_personalization_complete") {
        console.log("Personalization complete via WebSocket:", message.data);
        const data = { ...message.data, has_personalization: true };
        setPersonalizationData(data);
        setIsLoading(false);
        toast.success("Your personalized card is ready! 🎉");
      }
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
    isComplete: !!personalizationData?.has_personalization,
    refetch: fetchPersonalization,
  };
};
