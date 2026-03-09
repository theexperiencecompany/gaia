import { apiService } from "@/lib/api";
import type {
  CommunityWorkflowsResponse,
  CreateWorkflowPayload,
  UpdateWorkflowPayload,
  Workflow,
  WorkflowExecutionResponse,
  WorkflowExecutionsListResponse,
  WorkflowListResponse,
  WorkflowResponse,
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

function toQueryString(
  params?: Record<string, string | number | boolean | undefined>,
): string {
  if (!params) return "";
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      searchParams.set(key, String(value));
    }
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export const workflowApi = {
  listWorkflows: async (
    params?: ListWorkflowsParams,
  ): Promise<WorkflowListResponse> => {
    return apiService.get<WorkflowListResponse>(
      `/workflows${toQueryString(params)}`,
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
      `/workflows/${id}/executions${toQueryString(params)}`,
    );
  },

  getExploreWorkflows: async (
    params?: ListCommunityParams,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/explore${toQueryString(params)}`,
    );
  },

  getCommunityWorkflows: async (
    params?: ListCommunityParams,
  ): Promise<CommunityWorkflowsResponse> => {
    return apiService.get<CommunityWorkflowsResponse>(
      `/workflows/community${toQueryString(params)}`,
    );
  },

  getPublicWorkflow: async (id: string): Promise<{ workflow: Workflow }> => {
    return apiService.get<{ workflow: Workflow }>(`/workflows/public/${id}`);
  },
};
