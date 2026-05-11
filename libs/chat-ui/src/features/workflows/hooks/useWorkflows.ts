import { useEffect } from "react";
import type { Workflow } from "../api/workflowApi";
import { useWorkflowsStore } from "../stores/workflowsStore";

interface UseWorkflowsReturn {
  workflows: Workflow[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  addWorkflow: (workflow: Workflow) => void;
  updateWorkflow: (workflowId: string, updates: Partial<Workflow>) => void;
  removeWorkflow: (workflowId: string) => void;
  clearError: () => void;
}

export const useWorkflows = (autoFetch: boolean = true): UseWorkflowsReturn => {
  // Get state and actions from Zustand store (shared across all consumers)
  const {
    workflows,
    isLoading,
    error,
    fetchWorkflows,
    addWorkflow,
    updateWorkflow,
    removeWorkflow,
    clearError,
  } = useWorkflowsStore();

  // Auto-fetch on mount if enabled
  // fetchWorkflows is stable (defined in Zustand store, not recreated)
  useEffect(() => {
    if (autoFetch) fetchWorkflows();
  }, [autoFetch, fetchWorkflows]);

  return {
    workflows,
    isLoading,
    error,
    refetch: fetchWorkflows,
    addWorkflow,
    updateWorkflow,
    removeWorkflow,
    clearError,
  };
};
