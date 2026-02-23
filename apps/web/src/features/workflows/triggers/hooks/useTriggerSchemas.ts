/**
 * useTriggerSchemas Hook
 *
 * Fetches trigger schemas from backend API.
 * Backend is the single source of truth for schema definitions.
 */

import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import { workflowApi } from "@/features/workflows/api/workflowApi";

import type { TriggerSchema } from "../types";

export const useTriggerSchemas = (
  options?: Partial<UseQueryOptions<TriggerSchema[], Error>>,
) => {
  return useQuery({
    queryKey: ["triggerSchemas"],
    queryFn: async () => {
      const response = await workflowApi.getTriggerSchemas();
      return response;
    },
    staleTime: 24 * 60 * 60 * 1000, // 24 hours
    gcTime: 24 * 60 * 60 * 1000, // 24 hours
    refetchOnWindowFocus: false,
    ...options,
  });
};
