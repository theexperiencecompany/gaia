/**
 * useTriggerOptions Hook
 *
 * Fetches dynamic options for trigger configuration fields (e.g., channels, boards).
 */

import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import { workflowApi } from "@/features/workflows/api/workflowApi";

export interface TriggerOption {
  value: string;
  label: string;
}

export const useTriggerOptions = (
  integrationId: string,
  triggerSlug: string,
  fieldName: string,
  enabled: boolean = true,
  queryParams?: Record<string, string | number | boolean>,
  options?: Partial<UseQueryOptions<TriggerOption[], Error>>,
) => {
  return useQuery({
    queryKey: [
      "triggerOptions",
      integrationId,
      triggerSlug,
      fieldName,
      queryParams,
    ],
    queryFn: async () => {
      const response = await workflowApi.getTriggerOptions(
        integrationId,
        triggerSlug,
        fieldName,
        queryParams,
      );
      return response;
    },
    enabled: enabled && !!integrationId && !!triggerSlug && !!fieldName,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
    retry: 1, // Only retry once if it fails
    ...options,
  });
};
