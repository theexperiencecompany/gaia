import { useQuery } from "@tanstack/react-query";

import { apiService } from "@/lib/api/service";

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
    steps: Array<{ category: string }>;
  }>;
}

const fetchPersonalizationData = async (): Promise<PersonalizationData> => {
  return apiService.get<PersonalizationData>("/onboarding/personalization", {
    silent: true,
  });
};

/**
 * Fetch personalization data from API using React Query
 * for automatic request deduplication, caching, and revalidation.
 */
export const usePersonalizationData = (enabled: boolean = true) => {
  const query = useQuery({
    queryKey: ["personalization"],
    queryFn: fetchPersonalizationData,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 minutes - personalization data changes infrequently
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
  });

  return {
    personalizationData: query.data ?? null,
    isLoading: query.isLoading,
    isComplete: !!query.data?.has_personalization,
    refetch: query.refetch,
  };
};
