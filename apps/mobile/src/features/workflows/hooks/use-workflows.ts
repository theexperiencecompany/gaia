import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import type { Workflow } from "../types/workflow-types";

interface UseWorkflowsState {
  workflows: Workflow[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
}

interface UseWorkflowsReturn extends UseWorkflowsState {
  refetch: () => Promise<void>;
}

export function useWorkflows(): UseWorkflowsReturn {
  const [state, setState] = useState<UseWorkflowsState>({
    workflows: [],
    isLoading: true,
    isRefreshing: false,
    error: null,
  });

  const fetchWorkflows = useCallback(async (isRefresh = false) => {
    setState((prev) => ({
      ...prev,
      isLoading: !isRefresh,
      isRefreshing: isRefresh,
      error: null,
    }));
    try {
      const response = await workflowApi.listWorkflows({ limit: 50 });
      setState((prev) => ({
        ...prev,
        workflows: response.workflows,
        isLoading: false,
        isRefreshing: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        isRefreshing: false,
        error: err instanceof Error ? err.message : "Failed to load workflows",
      }));
    }
  }, []);

  useEffect(() => {
    void fetchWorkflows();
  }, [fetchWorkflows]);

  return {
    ...state,
    refetch: () => fetchWorkflows(true),
  };
}
