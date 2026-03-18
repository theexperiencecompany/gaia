import { buildQueryString } from "@gaia/shared/api";
import { apiService } from "@/lib/api";
import type { TriggerSchema } from "../types/trigger-types";
import type {
  CommunityWorkflowsResponse,
  CreateWorkflowPayload,
  UpdateWorkflowPayload,
  Workflow,
  WorkflowExecutionResponse,
  WorkflowExecutionsListResponse,
  WorkflowListResponse,
  WorkflowResponse,
  WorkflowStatusResponse,
} from "../types/workflow-types";

interface ListWorkflowsParams
  extends Record<string, string | number | boolean | undefined> {
  activated?: boolean;
  source?: string;
  limit?: number;
  skip?: number;
}

interface ListExecutionsParams
  extends Record<string, string | number | boolean | undefined> {
  limit?: number;
  offset?: number;
}

interface ListCommunityParams
  extends Record<string, string | number | boolean | undefined> {
  limit?: number;
  offset?: number;
}

export const workflowApi = {
  listWorkflows: async (
    params?: ListWorkflowsParams,
  ): Promise<WorkflowListResponse> => {
    return apiService.get<WorkflowListResponse>(
      `/workflows${buildQueryString(params)}`,
    );
  },

  getWorkflow: async (id: string): Promise<WorkflowResponse> => {
    return apiService.get<WorkflowResponse>(`/workflows/${id}`);
  },

  createWorkflow: async (
    payload: CreateWorkflowPayload,
  ): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>("/workflows", payload);
  },

  updateWorkflow: async (
    id: string,
    payload: UpdateWorkflowPayload,
  ): Promise<WorkflowResponse> => {
    return apiService.put<WorkflowResponse>(`/workflows/${id}`, payload);
  },

  deleteWorkflow: async (id: string): Promise<{ message: string }> => {
    return apiService.delete<{ message: string }>(`/workflows/${id}`);
  },

  activateWorkflow: async (id: string): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(`/workflows/${id}/activate`);
  },

  deactivateWorkflow: async (id: string): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(`/workflows/${id}/deactivate`);
  },

  executeWorkflow: async (id: string): Promise<WorkflowExecutionResponse> => {
    return apiService.post<WorkflowExecutionResponse>(
      `/workflows/${id}/execute`,
    );
  },

  getWorkflowExecutions: async (
    id: string,
    params?: ListExecutionsParams,
  ): Promise<WorkflowExecutionsListResponse> => {
    return apiService.get<WorkflowExecutionsListResponse>(
      `/workflows/${id}/executions${buildQueryString(params)}`,
    );
  },

  getExploreWorkflows: async (
    params?: ListCommunityParams,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/explore${buildQueryString(params)}`,
    );
  },

  getCommunityWorkflows: async (
    params?: ListCommunityParams,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/community${buildQueryString(params)}`,
    );
  },

  getPublicWorkflow: async (id: string): Promise<{ workflow: Workflow }> => {
    return apiService.get<{ workflow: Workflow }>(`/workflows/public/${id}`);
  },

  regenerateWorkflowSteps: async (
    id: string,
    options?: {
      instruction?: string;
      force_different_tools?: boolean;
    },
  ): Promise<WorkflowResponse> => {
    return apiService.post<WorkflowResponse>(
      `/workflows/${id}/regenerate-steps`,
      {
        instruction: options?.instruction || "Generate workflow steps",
        force_different_tools: options?.force_different_tools ?? true,
      },
    );
  },

  publishWorkflow: async (
    id: string,
  ): Promise<{ message: string; workflow_id: string }> => {
    return apiService.post<{ message: string; workflow_id: string }>(
      `/workflows/${id}/publish`,
    );
  },

  unpublishWorkflow: async (id: string): Promise<{ message: string }> => {
    return apiService.post<{ message: string }>(`/workflows/${id}/unpublish`);
  },

  getWorkflowStatus: async (id: string): Promise<WorkflowStatusResponse> => {
    return apiService.get<WorkflowStatusResponse>(`/workflows/${id}/status`);
  },

  getTriggerSchemas: async (): Promise<TriggerSchema[]> => {
    return apiService.get<TriggerSchema[]>("/triggers/schema");
  },

  generatePrompt: async (params: {
    title?: string;
    description?: string;
    existing_prompt?: string;
  }): Promise<{ prompt: string }> => {
    return apiService.post<{ prompt: string }>(
      "/workflows/generate-prompt",
      params,
    );
  },
};
