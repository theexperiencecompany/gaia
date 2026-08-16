import { useUsageSummary } from "@/features/settings/hooks/useUsage";

const BROWSER_TASK_FEATURE_KEY = "browser_task";

/** This month's browser-task usage, derived from the shared /usage/summary
 * feature map — there is no dedicated browser usage endpoint. */
export function useBrowserUsage() {
  const { data, isLoading } = useUsageSummary();
  const month = data?.features[BROWSER_TASK_FEATURE_KEY]?.periods.month;

  return {
    used: month?.used ?? 0,
    limit: month?.limit ?? 0,
    isLoading,
  };
}
