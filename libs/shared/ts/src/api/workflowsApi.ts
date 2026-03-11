/**
 * Shared workflow API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

export const WORKFLOW_ENDPOINTS = {
  list: "/workflows",
  create: "/workflows",
  get: (id: string) => `/workflows/${id}`,
  update: (id: string) => `/workflows/${id}`,
  delete: (id: string) => `/workflows/${id}`,
  activate: (id: string) => `/workflows/${id}/activate`,
  deactivate: (id: string) => `/workflows/${id}/deactivate`,
  execute: (id: string) => `/workflows/${id}/execute`,
  executions: (id: string) => `/workflows/${id}/executions`,
  status: (id: string) => `/workflows/${id}/status`,
  regenerateSteps: (id: string) => `/workflows/${id}/regenerate-steps`,
  publish: (id: string) => `/workflows/${id}/publish`,
  unpublish: (id: string) => `/workflows/${id}/unpublish`,
  resetToDefault: (id: string) => `/workflows/${id}/reset-to-default`,
  publicWorkflow: (id: string) => `/workflows/public/${id}`,
  fromTodo: "/workflows/from-todo",
  generatePrompt: "/workflows/generate-prompt",
  explore: "/workflows/explore",
  community: "/workflows/community",
  triggerSchemas: "/triggers/schema",
  triggerOptions: "/triggers/options",
} as const;

export interface WorkflowListParams {
  activated?: boolean;
  source?: string;
  limit?: number;
  skip?: number;
}

export interface WorkflowExecutionsParams {
  limit?: number;
  offset?: number;
}

export interface WorkflowCommunityParams {
  limit?: number;
  offset?: number;
}

export interface WorkflowCreateParams {
  title: string;
  description?: string;
  prompt: string;
  trigger_config?: Record<string, unknown>;
  steps?: Array<{
    title: string;
    category: string;
    description: string;
    order?: number;
  }>;
  execution_config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  generate_immediately?: boolean;
}

export interface WorkflowUpdateParams {
  title?: string;
  description?: string;
  prompt?: string;
  trigger_config?: Record<string, unknown>;
  activated?: boolean;
}

export interface WorkflowRegenerateParams {
  instruction?: string;
  force_different_tools?: boolean;
}

export interface WorkflowGeneratePromptParams {
  title?: string;
  description?: string;
  trigger_config?: Record<string, unknown>;
  existing_prompt?: string;
}

export interface WorkflowFromTodoParams {
  todo_id: string;
  todo_title: string;
  todo_description?: string;
}

export interface WorkflowTriggerOptionsParams {
  integration_id: string;
  trigger_slug: string;
  field_name: string;
  [key: string]: string | number | boolean | undefined;
}
