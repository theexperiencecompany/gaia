import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { DashboardHeatmapResponse } from "@/types/features/dashboardTypes";

import { dashboardApi } from "../api/dashboardApi";

/**
 * React Query hook for the contribution heatmap + current streak, derived
 * from completed todos across both assignees.
 */
export const useHeatmapQuery = (
  days = 365,
  options?: Partial<UseQueryOptions<DashboardHeatmapResponse, Error>>,
) => {
  return useQuery({
    queryKey: ["dashboard", "heatmap", days],
    queryFn: async (): Promise<DashboardHeatmapResponse> => {
      return await dashboardApi.fetchHeatmap(days);
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - a day's contributions rarely change after the fact
    gcTime: 30 * 60 * 1000, // 30 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
