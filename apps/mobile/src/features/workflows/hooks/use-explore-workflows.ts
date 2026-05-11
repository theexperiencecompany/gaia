import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import { WORKFLOW_COMMUNITY_PAGE_SIZE } from "../constants/timing";
import type { CommunityWorkflow } from "../types/workflow-types";

interface UseExploreWorkflowsState {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  error: string | null;
}

interface UseExploreWorkflowsReturn extends UseExploreWorkflowsState {
  refetch: () => Promise<void>;
}

export function useExploreWorkflows(): UseExploreWorkflowsReturn {
  const [state, setState] = useState<UseExploreWorkflowsState>({
    workflows: [],
    isLoading: false,
    error: null,
  });

  const fetchWorkflows = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await workflowApi.getExploreWorkflows({
        limit: WORKFLOW_COMMUNITY_PAGE_SIZE,
      });
      setState({
        workflows: response.workflows,
        isLoading: false,
        error: null,
      });
    } catch (err) {
      // Keep prior list on transient errors so the UI doesn't clobber data
      // — the screen surfaces a non-blocking inline retry instead.
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error:
          err instanceof Error
            ? err.message
            : "Failed to load explore workflows",
      }));
    }
  }, []);

  useEffect(() => {
    void fetchWorkflows();
  }, [fetchWorkflows]);

  return {
    ...state,
    refetch: fetchWorkflows,
  };
}
