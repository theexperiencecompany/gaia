/**
 * Workflow API service for unified workflow management.
 * Provides functions to interact with the workflow backend API.
 */

import type { GenerateWorkflowPromptRequest } from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import type {
  CommunityWorkflow,
  CreateWorkflowRequest,
  Workflow,
  WorkflowExecutionRequest,
} from "@/types/features/workflowTypes";

// Re-export types for convenience
export type { CommunityWorkflow, CreateWorkflowRequest, Workflow };

export interface TriggerOptionsQuery {
  parentValues?: string[];
  page?: number;
  search?: string;
}

export const workflowApi = {
  // Create a new workflow
  createWorkflow: (request: CreateWorkflowRequest) =>
    api.post("/api/v1/workflows", {
      body: request,
      silent: true, // useWorkflowCreation hook handles error display
    }),

  // List the user's workflows
  listWorkflows: () => api.get("/api/v1/workflows"),

  // Get a specific workflow
  getWorkflow: (workflowId: string, options?: { silent?: boolean }) =>
    api.get("/api/v1/workflows/{workflow_id}", {
      path: { workflow_id: workflowId },
      silent: options?.silent,
    }),

  // Update a workflow
  updateWorkflow: (
    workflowId: string,
    updates: {
      title?: string;
      description?: string;
      prompt?: string;
      icon?: string | null;
      icon_color?: string | null;
      trigger_config?: CreateWorkflowRequest["trigger_config"];
      activated?: boolean;
      notify_on_completion?: boolean;
      integration_ids?: string[];
    },
  ) =>
    api.put("/api/v1/workflows/{workflow_id}", {
      path: { workflow_id: workflowId },
      body: updates,
      successMessage: "Workflow updated successfully",
      errorMessage: "Failed to update workflow",
    }),

  // Delete a workflow
  deleteWorkflow: (workflowId: string) =>
    api.delete("/api/v1/workflows/{workflow_id}", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow deleted successfully",
      errorMessage: "Failed to delete workflow",
    }),

  // Activate a workflow
  activateWorkflow: (workflowId: string) =>
    api.post("/api/v1/workflows/{workflow_id}/activate", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow activated successfully",
      errorMessage: "Failed to activate workflow",
    }),

  // Deactivate a workflow
  deactivateWorkflow: (workflowId: string) =>
    api.post("/api/v1/workflows/{workflow_id}/deactivate", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow deactivated successfully",
      errorMessage: "Failed to deactivate workflow",
    }),

  // Regenerate workflow steps
  regenerateWorkflowSteps: (
    workflowId: string,
    options?: {
      instruction?: string;
      force_different_tools?: boolean;
      integration_ids?: string[];
    },
  ) =>
    api.post("/api/v1/workflows/{workflow_id}/regenerate-steps", {
      path: { workflow_id: workflowId },
      body: {
        instruction: options?.instruction || "Generate workflow steps",
        force_different_tools: options?.force_different_tools ?? true,
        integration_ids: options?.integration_ids,
      },
      errorMessage: "Failed to regenerate workflow steps",
    }),

  // Execute a workflow
  executeWorkflow: (workflowId: string, request?: WorkflowExecutionRequest) =>
    api.post("/api/v1/workflows/{workflow_id}/execute", {
      path: { workflow_id: workflowId },
      body: request || {},
      successMessage: "Workflow execution started",
      errorMessage: "Failed to execute workflow",
    }),

  // Get workflow execution history
  getWorkflowExecutions: (
    workflowId: string,
    limit: number = 10,
    offset: number = 0,
  ) =>
    api.get("/api/v1/workflows/{workflow_id}/executions", {
      path: { workflow_id: workflowId },
      query: { limit, offset },
      silent: true,
    }),

  // Create workflow from todo (migration helper)
  createWorkflowFromTodo: (
    todoId: string,
    todoTitle: string,
    todoDescription?: string,
  ) =>
    api.post("/api/v1/workflows/from-todo", {
      body: {
        todo_id: todoId,
        todo_title: todoTitle,
        todo_description: todoDescription,
      },
      successMessage: "Workflow created from todo successfully",
      errorMessage: "Failed to create workflow from todo",
    }),

  // Publish workflow to community
  publishWorkflow: (workflowId: string) =>
    api.post("/api/v1/workflows/{workflow_id}/publish", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow published to community",
      errorMessage: "Failed to publish workflow",
    }),

  // Unpublish workflow from community
  unpublishWorkflow: (workflowId: string) =>
    api.post("/api/v1/workflows/{workflow_id}/unpublish", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow unpublished from community",
      errorMessage: "Failed to unpublish workflow",
    }),

  // Get explore workflows for discover section
  getExploreWorkflows: (limit: number = 25, offset: number = 0) =>
    api.get("/api/v1/workflows/explore", {
      query: { limit, offset },
      errorMessage: "Failed to fetch explore workflows",
    }),

  // Get public workflows from community
  getCommunityWorkflows: (limit: number = 20, offset: number = 0) =>
    api.get("/api/v1/workflows/community", {
      query: { limit, offset },
      errorMessage: "Failed to fetch community workflows",
    }),

  // Get a public workflow without authentication (for server-side rendering)
  getPublicWorkflow: (workflowId: string) =>
    api.get("/api/v1/workflows/public/{workflow_ref}", {
      path: { workflow_ref: workflowId },
      errorMessage: "Failed to fetch public workflow",
    }),

  // Generate or improve workflow instructions using AI
  generatePrompt: (params: GenerateWorkflowPromptRequest) =>
    api.post("/api/v1/workflows/generate-prompt", {
      body: params,
      silent: true,
    }),

  // Reset a system workflow to its default definition
  resetToDefault: (workflowId: string) =>
    api.post("/api/v1/workflows/{workflow_id}/reset-to-default", {
      path: { workflow_id: workflowId },
      successMessage: "Workflow reset to default",
      errorMessage: "Failed to reset workflow",
    }),

  // silent: non-critical metadata; UI falls back to the slug, never toast.
  getTriggerSchemas: () => api.get("/api/v1/triggers/schema", { silent: true }),

  // Get dynamic options for trigger configuration field; `parentValues` are
  // the ids of the parent selection for cascading fields (sheets of a
  // spreadsheet), sent comma-separated as the route reads them. `page` and
  // `search` are honoured by the handlers that page/filter (GitHub repos).
  getTriggerOptions: async (
    integrationId: string,
    triggerSlug: string,
    fieldName: string,
    { parentValues, page, search }: TriggerOptionsQuery = {},
  ) => {
    const response = await api.get("/api/v1/triggers/options", {
      query: {
        integration_id: integrationId,
        trigger_slug: triggerSlug,
        field_name: fieldName,
        parent_values: parentValues?.join(","),
        page,
        search,
      },
      errorMessage: "Failed to fetch trigger options",
      silent: true, // Fail silently if options not available
    });
    return response.options;
  },
};
