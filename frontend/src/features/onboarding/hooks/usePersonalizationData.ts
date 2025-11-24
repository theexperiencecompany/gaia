import { useEffect,useState } from "react";

import { apiService } from "@/lib/api";

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

interface UsePersonalizationDataReturn {
  personalizationData: PersonalizationData | null;
  isLoading: boolean;
  isComplete: boolean;
  refetch: () => Promise<void>;
}

/**
 * Fetch personalization data from API
 */
export const usePersonalizationData = (
  enabled: boolean = true,
): UsePersonalizationDataReturn => {
  const [personalizationData, setPersonalizationData] =
    useState<PersonalizationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchData = async () => {
    if (!enabled) return;

    try {
      setIsLoading(true);
      const data = await apiService.get<PersonalizationData>(
        "/onboarding/personalization",
        { silent: true },
      );

      // Only set if personalization is complete
      if (data.has_personalization) {
        setPersonalizationData(data);
      }
    } catch (error) {
      console.error("Failed to fetch personalization data:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [enabled]);

  return {
    personalizationData,
    isLoading,
    isComplete: !!personalizationData?.has_personalization,
    refetch: fetchData,
  };
};
