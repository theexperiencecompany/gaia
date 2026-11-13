import { useQuery } from "@tanstack/react-query";

import { workflowKeys } from "../api/queryKeys";
import { type Workflow, workflowApi } from "../api/workflowApi";

/** How long the workflow list stays fresh before a remount refetches it. */
const WORKFLOWS_STALE_TIME = 60 * 1000;

interface UseWorkflowsReturn {
  workflows: Workflow[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<unknown>;
}

const EMPTY_WORKFLOWS: Workflow[] = [];

export const useWorkflows = (enabled: boolean = true): UseWorkflowsReturn => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: workflowKeys.list(),
    queryFn: async () => (await workflowApi.listWorkflows()).workflows,
    staleTime: WORKFLOWS_STALE_TIME,
    enabled,
  });

  return {
    workflows: data ?? EMPTY_WORKFLOWS,
    isLoading,
    error: error ? error.message : null,
    refetch,
  };
};
