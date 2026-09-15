/**
 * useTriggerOptions Hook
 *
 * Fetches dynamic options for trigger configuration fields (e.g., channels, boards).
 */

import type { TriggerOption, TriggerOptionGroup } from "@shared/api/generated";

export type { TriggerOption } from "@shared/api/generated";

import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import { workflowApi } from "@/features/workflows/api/workflowApi";

/** One entry of `/triggers/options`: a flat option, or a labelled group of them. */
export type TriggerOptionEntry = TriggerOption | TriggerOptionGroup;

/** Narrows an entry to a flat option; handlers that only know flat lists drop groups. */
export const isTriggerOption = (
  entry: TriggerOptionEntry,
): entry is TriggerOption => "value" in entry;

export const useTriggerOptions = (
  integrationId: string,
  triggerSlug: string,
  fieldName: string,
  enabled: boolean = true,
  parentValues?: string[],
  options?: Partial<UseQueryOptions<TriggerOptionEntry[], Error>>,
) => {
  return useQuery({
    queryKey: [
      "triggerOptions",
      integrationId,
      triggerSlug,
      fieldName,
      parentValues,
    ],
    queryFn: async () => {
      const response = await workflowApi.getTriggerOptions(
        integrationId,
        triggerSlug,
        fieldName,
        { parentValues },
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
