import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import type { Workflow, WorkflowExecution } from "../types/workflow-types";

interface UseWorkflowDetailState {
  workflow: Workflow | null;
  executions: WorkflowExecution[];
  executionsTotal: number;
  hasMoreExecutions: boolean;
  isLoading: boolean;
  isLoadingExecutions: boolean;
  error: string | null;
}

interface UseWorkflowDetailReturn extends UseWorkflowDetailState {
  refetch: () => Promise<void>;
  refetchExecutions: () => Promise<void>;
  loadMoreExecutions: () => Promise<void>;
}

const EXECUTIONS_PAGE_SIZE = 10;

export function useWorkflowDetail(
  workflowId: string | null,
): UseWorkflowDetailReturn {
  const [state, setState] = useState<UseWorkflowDetailState>({
    workflow: null,
    executions: [],
    executionsTotal: 0,
    hasMoreExecutions: false,
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

  const fetchExecutions = useCallback(
    async (reset = true) => {
      if (!workflowId) return;
      setState((prev) => ({ ...prev, isLoadingExecutions: true }));
      try {
        const offset = reset ? 0 : state.executions.length;
        const response = await workflowApi.getWorkflowExecutions(workflowId, {
          limit: EXECUTIONS_PAGE_SIZE,
          offset,
        });
        setState((prev) => ({
          ...prev,
          executions: reset
            ? response.executions
            : [...prev.executions, ...response.executions],
          executionsTotal: response.total,
          hasMoreExecutions: response.has_more,
          isLoadingExecutions: false,
        }));
      } catch {
        setState((prev) => ({ ...prev, isLoadingExecutions: false }));
      }
    },
    [workflowId, state.executions.length],
  );

  useEffect(() => {
    void fetchWorkflow();
    void fetchExecutions(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId]);

  const loadMoreExecutions = useCallback(async () => {
    if (!state.isLoadingExecutions && state.hasMoreExecutions) {
      await fetchExecutions(false);
    }
  }, [state.isLoadingExecutions, state.hasMoreExecutions, fetchExecutions]);

  return {
    ...state,
    refetch: fetchWorkflow,
    refetchExecutions: () => fetchExecutions(true),
    loadMoreExecutions,
  };
}
