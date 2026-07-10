import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { DashboardTodayResponse } from "@/types/features/dashboardTypes";

import { dashboardApi } from "../api/dashboardApi";

export const TODAY_QUERY_KEY = ["dashboard", "today"] as const;

/**
 * React Query hook for the Today view. Freshness is layered: websocket
 * invalidation (see `useTodayLiveUpdates`) is the primary signal, window
 * focus refetch is the safety net, and a slow poll runs only while GAIA
 * actually has work in flight.
 */
export const useTodayQuery = (
  options?: Partial<UseQueryOptions<DashboardTodayResponse, Error>>,
) => {
  return useQuery({
    queryKey: TODAY_QUERY_KEY,
    queryFn: async (): Promise<DashboardTodayResponse> => {
      return await dashboardApi.fetchToday();
    },
    staleTime: 30 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 2,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && data.in_flight.length > 0 ? 20 * 1000 : false;
    },
    ...options,
  });
};
