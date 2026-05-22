import { useCallback, useEffect, useRef, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import { WORKFLOW_EXECUTIONS_PAGE_SIZE } from "../constants/timing";
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

  // Track current pagination offset in a ref so the callback identity stays
  // stable as new executions arrive (item 1 in the workflows-rebuild plan —
  // including state.executions.length in deps caused the callback to be
  // recreated on every fetch and re-trigger the effect).
  const executionsOffsetRef = useRef(0);

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
      const offset = reset ? 0 : executionsOffsetRef.current;
      try {
        const response = await workflowApi.getWorkflowExecutions(workflowId, {
          limit: WORKFLOW_EXECUTIONS_PAGE_SIZE,
          offset,
        });
        executionsOffsetRef.current = offset + response.executions.length;
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
    [workflowId],
  );

  useEffect(() => {
    executionsOffsetRef.current = 0;
    void fetchWorkflow();
    void fetchExecutions(true);
  }, [fetchWorkflow, fetchExecutions]);

  const loadMoreExecutions = useCallback(async () => {
    if (!state.isLoadingExecutions && state.hasMoreExecutions) {
      await fetchExecutions(false);
    }
  }, [state.isLoadingExecutions, state.hasMoreExecutions, fetchExecutions]);

  const refetchExecutions = useCallback(
    () => fetchExecutions(true),
    [fetchExecutions],
  );

  return {
    ...state,
    refetch: fetchWorkflow,
    refetchExecutions,
    loadMoreExecutions,
  };
}
