import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { Briefing } from "@/types/features/briefingTypes";

import { briefingApi } from "../api/briefingApi";

/**
 * React Query hook for the user's past briefings (archive), most recent first.
 */
export const useBriefingsQuery = (
  limit = 30,
  options?: Partial<UseQueryOptions<Briefing[], Error>>,
) => {
  return useQuery({
    queryKey: ["briefings", limit],
    queryFn: async (): Promise<Briefing[]> => {
      return await briefingApi.fetchBriefings(limit);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
