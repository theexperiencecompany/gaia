import { useQuery } from "@tanstack/react-query";
import { browserApi } from "../api/browserApi";
import type { BrowserTask } from "../types";

const browserTasksKey = ["browser-tasks"] as const;

export function useBrowserTasks() {
  const query = useQuery({
    queryKey: browserTasksKey,
    queryFn: () => browserApi.listTasks(),
  });

  return {
    tasks: (query.data ?? []) as BrowserTask[],
    isLoading: query.isLoading,
    error: query.error as Error | null,
    refetch: query.refetch,
  };
}
