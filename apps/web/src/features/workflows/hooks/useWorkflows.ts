import { useQuery } from "@tanstack/react-query";

import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

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
  // A user's workflows need their session; a signed-out visitor would get a 401.
  const userId = useCurrentUser()?.user_id;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: workflowKeys.list(),
    queryFn: async () => (await workflowApi.listWorkflows()).workflows,
    staleTime: WORKFLOWS_STALE_TIME,
    enabled: enabled && Boolean(userId),
  });

  return {
    workflows: data ?? EMPTY_WORKFLOWS,
    isLoading,
    error: error ? error.message : null,
    refetch,
  };
};
