import { ApiError } from "@shared/api";
import { useState } from "react";

import {
  type CreateWorkflowRequest,
  type Workflow,
  workflowApi,
} from "../api/workflowApi";

export const useWorkflowCreation = (): UseWorkflowCreationReturn => {
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdWorkflow, setCreatedWorkflow] = useState<Workflow | null>(null);

  const createWorkflow = async (
    request: CreateWorkflowRequest,
  ): Promise<{ success: boolean; workflow?: Workflow }> => {
    try {
      setIsCreating(true);
      setError(null);
      const response = await workflowApi.createWorkflow(request);

      setCreatedWorkflow(response.workflow);
      // Note: Store updates are handled by the caller (WorkflowModal)
      // to avoid duplicate additions

      return { success: true, workflow: response.workflow };
    } catch (err) {
      console.error("useWorkflowCreation: API call failed:", err);

      const envelope = err instanceof ApiError ? err.envelope : undefined;

      // Sometimes the workflow is created but returns an error status
      // Check if we have a workflow in the error response
      const createdDespiteError = envelope?.workflow as Workflow | undefined;
      if (createdDespiteError) {
        console.warn(
          "Workflow was created despite error status, treating as success",
        );
        setCreatedWorkflow(createdDespiteError);
        // Note: Store updates are handled by the caller (WorkflowModal)

        return { success: true, workflow: createdDespiteError };
      }

      setError(
        envelope?.message ??
          (err instanceof Error ? err.message : "Failed to create workflow"),
      );
      return { success: false };
    } finally {
      setIsCreating(false);
    }
  };

  const clearError = () => setError(null);

  const reset = () => {
    setIsCreating(false);
    setError(null);
    setCreatedWorkflow(null);
  };

  return {
    isCreating,
    error,
    createdWorkflow,
    createWorkflow,
    clearError,
    reset,
  };
};

interface UseWorkflowCreationReturn {
  isCreating: boolean;
  error: string | null;
  createdWorkflow: Workflow | null;
  createWorkflow: (
    request: CreateWorkflowRequest,
  ) => Promise<{ success: boolean; workflow?: Workflow }>;
  clearError: () => void;
  reset: () => void;
}
