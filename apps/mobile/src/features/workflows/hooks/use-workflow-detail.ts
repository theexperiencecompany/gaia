import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import type { Workflow, WorkflowExecution } from "../types/workflow-types";

interface UseWorkflowDetailState {
  workflow: Workflow | null;
  executions: WorkflowExecution[];
  isLoading: boolean;
  isLoadingExecutions: boolean;
  error: string | null;
}

interface UseWorkflowDetailReturn extends UseWorkflowDetailState {
  refetch: () => Promise<void>;
  refetchExecutions: () => Promise<void>;
}

export function useWorkflowDetail(
  workflowId: string | null,
): UseWorkflowDetailReturn {
  const [state, setState] = useState<UseWorkflowDetailState>({
    workflow: null,
    executions: [],
    isLoading: false,
    isLoadingExecutions: false,
    error: null,
  });

  const fetchWorkflow = useCallback(async () => {
    if (!workflowId) return;
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await workflowApi.getWorkflow(workflowId);
      setState((prev) => ({
        ...prev,
        workflow: response.workflow,
        isLoading: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load workflow",
      }));
    }
  }, [workflowId]);

  const fetchExecutions = useCallback(async () => {
    if (!workflowId) return;
    setState((prev) => ({ ...prev, isLoadingExecutions: true }));
    try {
      const response = await workflowApi.getWorkflowExecutions(workflowId, {
        limit: 20,
      });
      setState((prev) => ({
        ...prev,
        executions: response.executions,
        isLoadingExecutions: false,
      }));
    } catch {
      setState((prev) => ({ ...prev, isLoadingExecutions: false }));
    }
  }, [workflowId]);

  useEffect(() => {
    void fetchWorkflow();
    void fetchExecutions();
  }, [fetchWorkflow, fetchExecutions]);

  return {
    ...state,
    refetch: fetchWorkflow,
    refetchExecutions: fetchExecutions,
  };
}
