import { useCallback, useEffect, useState } from "react";

import { Workflow, workflowApi } from "../api/workflowApi";

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
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [isLoading, setIsLoading] = useState(autoFetch);
  const [error, setError] = useState<string | null>(null);

  const fetchWorkflows = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      const response = await workflowApi.listWorkflows();
      setWorkflows(response.workflows);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to fetch workflows";
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const addWorkflow = useCallback((workflow: Workflow) => {
    setWorkflows((prev) => [workflow, ...prev]);
  }, []);

  const updateWorkflow = useCallback(
    (workflowId: string, updates: Partial<Workflow>) => {
      setWorkflows((prev) =>
        prev.map((workflow) =>
          workflow.id === workflowId ? { ...workflow, ...updates } : workflow,
        ),
      );
    },
    [],
  );

  const removeWorkflow = useCallback((workflowId: string) => {
    setWorkflows((prev) =>
      prev.filter((workflow) => workflow.id !== workflowId),
    );
  }, []);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  // Auto-fetch on mount if enabled
  useEffect(() => {
    if (autoFetch) {
      fetchWorkflows();
    }
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
