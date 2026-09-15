import { useQuery } from "@tanstack/react-query";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { workflowApi } from "../api/workflowApi";

const EXPLORE_WORKFLOWS_QUERY_KEY = ["explore-workflows"] as const;

const EXPLORE_WORKFLOWS_STALE_TIME = 5 * 60 * 1000;
const EXPLORE_WORKFLOWS_LIMIT = 50;

interface UseExploreWorkflowsReturn {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export const useExploreWorkflows = (
  enabled = true,
): UseExploreWorkflowsReturn => {
  const query = useQuery({
    queryKey: EXPLORE_WORKFLOWS_QUERY_KEY,
    queryFn: async () =>
      (await workflowApi.getExploreWorkflows(EXPLORE_WORKFLOWS_LIMIT, 0))
        .workflows,
    staleTime: EXPLORE_WORKFLOWS_STALE_TIME,
    enabled,
  });

  return {
    workflows: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
};
