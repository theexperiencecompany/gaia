import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
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
      const response = await workflowApi.getExploreWorkflows({ limit: 12 });
      setState((prev) => ({
        ...prev,
        workflows: response.workflows,
        isLoading: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error:
          err instanceof Error
            ? err.message
            : "Failed to load explore workflows",
        workflows: [],
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
