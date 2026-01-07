import { useInfiniteQuery } from "@tanstack/react-query";
import { workflowApi } from "@/features/workflows/api/workflowApi";

export interface TriggerOption {
  value: string;
  label: string;
  [key: string]: unknown;
}

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
    queryFn: async ({ pageParam = 1 }) => {
      // Call with queryParams ({ page, search })
      return workflowApi.getTriggerOptions(
        integrationId,
        triggerSlug,
        fieldName,
        { page: pageParam, search },
      );
    },
    getNextPageParam: (lastPage, allPages) => {
      // If last page has no options or fewer than expected (e.g. 50), stop
      if (!lastPage || lastPage.length < 50) return undefined;
      return allPages.length + 1;
    },
    initialPageParam: 1,
    enabled: enabled && !!integrationId && !!triggerSlug && !!fieldName,
  });
};
