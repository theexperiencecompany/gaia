/**
 * useInfiniteTriggerOptions Hook
 *
 * Pages through the dynamic options of a trigger field for handlers that
 * page them (GitHub repositories); a new `search` starts again from page 1.
 */

import { useInfiniteQuery } from "@tanstack/react-query";

import { workflowApi } from "@/features/workflows/api/workflowApi";

/**
 * Options per page — the `per_page` the GitHub handler requests
 * (`apps/api/app/services/triggers/handlers/github.py`). A shorter page is
 * the last one.
 */
export const TRIGGER_OPTIONS_PAGE_SIZE = 100;

export const useInfiniteTriggerOptions = (
  integrationId: string,
  triggerSlug: string,
  fieldName: string,
  enabled: boolean = true,
  search: string = "",
) => {
  return useInfiniteQuery({
    queryKey: [
      "triggerOptions",
      integrationId,
      triggerSlug,
      fieldName,
      "infinite",
      search,
    ],
    queryFn: ({ pageParam }) =>
      workflowApi.getTriggerOptions(integrationId, triggerSlug, fieldName, {
        page: pageParam,
        search,
      }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < TRIGGER_OPTIONS_PAGE_SIZE
        ? undefined
        : allPages.length + 1,
    enabled: enabled && !!integrationId && !!triggerSlug && !!fieldName,
  });
};
