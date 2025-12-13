/**
 * Workflow API service for unified workflow management.
 * Provides functions to interact with the workflow backend API.
 */

import { apiService } from "@/lib/api";
import type {
  CommunityWorkflow,
  CommunityWorkflowsResponse,
  CreateWorkflowRequest,
  Workflow,
  WorkflowExecutionRequest,
  WorkflowExecutionResponse,
  WorkflowListResponse,
  WorkflowResponse,
  WorkflowStatusResponse,
} from "@/types/features/workflowTypes";

// Re-export types for convenience
export type { CommunityWorkflow, CreateWorkflowRequest, Workflow };

export const workflowApi = {
  // Create a new workflow
  createWorkflow: async (
    request: CreateWorkflowRequest,
  ): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>("/workflows", request, {
      errorMessage: "Failed to create workflow",
    });
  },

  // List workflows with filtering
  listWorkflows: async (params?: {
    activated?: boolean;
    source?: string;
    limit?: number;
    skip?: number;
  }): Promise<WorkflowListResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.activated !== undefined)
      searchParams.append("activated", params.activated.toString());
    if (params?.source) searchParams.append("source", params.source);
    if (params?.limit) searchParams.append("limit", params.limit.toString());
    if (params?.skip) searchParams.append("skip", params.skip.toString());

    const queryString = searchParams.toString();
    const url = queryString ? `/workflows?${queryString}` : "/workflows";

    return apiService.get<WorkflowListResponse>(url);
  },

  // Get a specific workflow
  getWorkflow: async (
    workflowId: string,
    options?: { silent?: boolean },
  ): Promise<WorkflowResponse> => {
    return apiService.get<WorkflowResponse>(`/workflows/${workflowId}`, {
      silent: options?.silent,
    });
  },

  // Update a workflow
  updateWorkflow: async (
    workflowId: string,
    updates: Partial<CreateWorkflowRequest>,
  ): Promise<WorkflowResponse> => {
    return apiService.put<WorkflowResponse>(
      `/workflows/${workflowId}`,
      updates,
      {
        successMessage: "Workflow updated successfully",
        errorMessage: "Failed to update workflow",
      },
    );
  },

  // Delete a workflow
  deleteWorkflow: async (workflowId: string): Promise<{ message: string }> => {
    return apiService.delete<{ message: string }>(`/workflows/${workflowId}`, {
      successMessage: "Workflow deleted successfully",
      errorMessage: "Failed to delete workflow",
    });
  },

  // Activate a workflow
  activateWorkflow: async (workflowId: string): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(
      `/workflows/${workflowId}/activate`,
      {},
      {
        successMessage: "Workflow activated successfully",
        errorMessage: "Failed to activate workflow",
      },
    );
  },

  // Deactivate a workflow
  deactivateWorkflow: async (workflowId: string): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(
      `/workflows/${workflowId}/deactivate`,
      {},
      {
        successMessage: "Workflow deactivated successfully",
        errorMessage: "Failed to deactivate workflow",
      },
    );
  },

  // Regenerate workflow steps
  regenerateWorkflowSteps: async (
    workflowId: string,
    options?: {
      instruction?: string;
      force_different_tools?: boolean;
    },
  ): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(
      `/workflows/${workflowId}/regenerate-steps`,
      {
        instruction: options?.instruction || "Generate workflow steps",
        force_different_tools: options?.force_different_tools ?? true,
      },
      {
        errorMessage: "Failed to regenerate workflow steps",
      },
    );
  },

  // Execute a workflow
  executeWorkflow: async (
    workflowId: string,
    request?: WorkflowExecutionRequest,
  ): Promise<WorkflowExecutionResponse> => {
    return apiService.post<WorkflowExecutionResponse>(
      `/workflows/${workflowId}/execute`,
      request || {},
      {
        successMessage: "Workflow execution started",
        errorMessage: "Failed to execute workflow",
      },
    );
  },

  // Get workflow status
  getWorkflowStatus: async (
    workflowId: string,
  ): Promise<WorkflowStatusResponse> => {
    return apiService.get<WorkflowStatusResponse>(
      `/workflows/${workflowId}/status`,
      {
        silent: true, // Don't show success/error toasts for polling
      },
    );
  },

  // Create workflow from todo (migration helper)
  createWorkflowFromTodo: async (
    todoId: string,
    todoTitle: string,
    todoDescription?: string,
  ): Promise<{ workflow: Workflow; message: string }> => {
    return apiService.post<{ workflow: Workflow; message: string }>(
      "/workflows/from-todo",
      {
        todo_id: todoId,
        todo_title: todoTitle,
        todo_description: todoDescription,
      },
      {
        successMessage: "Workflow created from todo successfully",
        errorMessage: "Failed to create workflow from todo",
      },
    );
  },

  // Publish workflow to community
  publishWorkflow: async (
    workflowId: string,
  ): Promise<{ message: string; workflow_id: string }> => {
    return apiService.post<{ message: string; workflow_id: string }>(
      `/workflows/${workflowId}/publish`,
      {},
      {
        successMessage: "Workflow published to community",
        errorMessage: "Failed to publish workflow",
      },
    );
  },

  // Unpublish workflow from community
  unpublishWorkflow: async (
    workflowId: string,
  ): Promise<{ message: string }> => {
    return apiService.post<{ message: string }>(
      `/workflows/${workflowId}/unpublish`,
      {},
      {
        successMessage: "Workflow unpublished from community",
        errorMessage: "Failed to unpublish workflow",
      },
    );
  },

  // Get explore workflows for discover section
  getExploreWorkflows: async (
    limit: number = 25,
    offset: number = 0,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/explore?limit=${limit}&offset=${offset}`,
      {
        errorMessage: "Failed to fetch explore workflows",
      },
    );
  },

  // Get public workflows from community
  getCommunityWorkflows: async (
    limit: number = 20,
    offset: number = 0,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/community?limit=${limit}&offset=${offset}`,
      {
        errorMessage: "Failed to fetch community workflows",
      },
    );
  },

  // Get a public workflow without authentication (for server-side rendering)
  getPublicWorkflow: async (workflowId: string): Promise<WorkflowResponse> => {
    return apiService.get<WorkflowResponse>(`/workflows/public/${workflowId}`, {
      errorMessage: "Failed to fetch public workflow",
    });
  },
};
