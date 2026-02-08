import { useState } from "react";

import {
  type CreateWorkflowRequest,
  type Workflow,
  workflowApi,
} from "../api/workflowApi";
import { useWorkflowsStore } from "../stores/workflowsStore";

export const useWorkflowCreation = (): UseWorkflowCreationReturn => {
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdWorkflow, setCreatedWorkflow] = useState<Workflow | null>(null);

  const { fetchWorkflows, addWorkflow } = useWorkflowsStore();

  const createWorkflow = async (
    request: CreateWorkflowRequest,
  ): Promise<{ success: boolean; workflow?: Workflow }> => {
    try {
      setIsCreating(true);
      setError(null);

      console.log(
        "useWorkflowCreation: Making API call with request:",
        request,
      );
      const response = await workflowApi.createWorkflow(request);
      console.log("useWorkflowCreation: API response:", response);

      setCreatedWorkflow(response.workflow);
      addWorkflow(response.workflow);

      return { success: true, workflow: response.workflow };
    } catch (err) {
      console.error("useWorkflowCreation: API call failed:", err);

      // Check if this is a network error vs server error
      const error = err as Error & {
        response?: {
          status?: number;
          data?: { workflow?: Workflow; detail?: string };
        };
      };
      const statusCode = error?.response?.status;
      const responseData = error?.response?.data;

      console.error("Error status code:", statusCode);
      console.error("Error response data:", responseData);

      // Sometimes the workflow is created but returns an error status
      // Check if we have a workflow in the error response
      if (responseData?.workflow) {
        console.warn(
          "Workflow was created despite error status, treating as success",
        );
        setCreatedWorkflow(responseData.workflow);

        // Add to store and refetch even on error if workflow exists
        addWorkflow(responseData.workflow);
        await fetchWorkflows();

        return { success: true, workflow: responseData.workflow };
      }

      // Extract error detail from API response
      // FastAPI returns {detail: "..."} or {detail: {message: "..."}} for 429 errors
      let errorMessage = "Failed to create workflow";
      if (responseData?.detail) {
        if (typeof responseData.detail === "string") {
          errorMessage = responseData.detail;
        } else if (
          typeof responseData.detail === "object" &&
          responseData.detail !== null
        ) {
          const detail = responseData.detail as { message?: string };
          errorMessage = detail.message || errorMessage;
        }
      } else if (error instanceof Error) {
        errorMessage = error.message;
      }
      setError(errorMessage);
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
