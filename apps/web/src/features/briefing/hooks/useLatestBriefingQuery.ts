import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { Briefing } from "@/types/features/briefingTypes";

import { briefingApi } from "../api/briefingApi";

/**
 * React Query hook for the user's most recent briefing (or null if none yet).
 */
export const useLatestBriefingQuery = (
  options?: Partial<UseQueryOptions<Briefing | null, Error>>,
) => {
  return useQuery({
    queryKey: ["briefings", "latest"],
    queryFn: async (): Promise<Briefing | null> => {
      return await briefingApi.fetchLatestBriefing();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - a new briefing lands at most once a day
    gcTime: 30 * 60 * 1000, // 30 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
