import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";
import { firstStepsApi } from "../api/firstStepsApi";

export const FIRST_STEPS_QUERY_KEY = ["first-steps"];

/**
 * React Query hook for the activation checklist. Mounted app-wide via
 * FirstStepsWidget in the (main) layout, so a long staleTime avoids refetch
 * storms on every route change — mutations invalidate this key explicitly.
 */
export const useFirstStepsQuery = (
  options?: Partial<UseQueryOptions<FirstStepsResponse, Error>>,
) => {
  return useQuery({
    queryKey: FIRST_STEPS_QUERY_KEY,
    queryFn: firstStepsApi.fetchFirstSteps,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000,
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};
