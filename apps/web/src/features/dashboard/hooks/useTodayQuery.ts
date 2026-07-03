import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { DashboardTodayResponse } from "@/types/features/dashboardTypes";

import { dashboardApi } from "../api/dashboardApi";

/**
 * React Query hook for today's Mission Control timeline — todos + calendar
 * events + workflow executions, interleaved chronologically by the server.
 */
export const useTodayQuery = (
  options?: Partial<UseQueryOptions<DashboardTodayResponse, Error>>,
) => {
  return useQuery({
    queryKey: ["dashboard", "today"],
    queryFn: async (): Promise<DashboardTodayResponse> => {
      return await dashboardApi.fetchToday();
    },
    staleTime: 60 * 1000, // 1 minute - today's board shifts as GAIA works
    gcTime: 10 * 60 * 1000, // 10 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
