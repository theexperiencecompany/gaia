// Workflow-related types for comprehensive workflow management

import type {
  EmailTriggerConfig,
  ManualTriggerConfig,
  ScheduleTriggerConfig,
  TriggerConfig,
} from "@/config/registries/triggerRegistry";

// Legacy workflow step data (for message components)
export interface WorkflowStepData {
  id: string;
  title: string;
  description: string;
  tool_name: string;
  tool_category: string;
}

// Legacy workflow data (for message components)
export interface WorkflowData {
  id: string;
  title: string;
  description: string;
  steps: WorkflowStepData[];
}

// Complete workflow step type for API operations
export interface WorkflowStepType {
  id: string;
  title: string;
  tool_name: string;
  tool_category: string;
  description: string;
  tool_inputs: Record<string, unknown>;
  order: number;
  executed_at?: string;
  result?: Record<string, unknown>;
}

// Re-export trigger types for convenience
export type {
  EmailTriggerConfig,
  ManualTriggerConfig,
  ScheduleTriggerConfig,
  TriggerConfig,
};

// Execution configuration for workflows
export interface ExecutionConfig {
  method: "chat" | "background" | "hybrid";
  timeout_seconds: number;
  max_retries: number;
  retry_delay_seconds: number;
  notify_on_completion: boolean;
  notify_on_failure: boolean;
}

// Workflow metadata tracking
export interface WorkflowMetadata {
  created_from: "chat" | "modal" | "todo" | "template" | "api";
  template_id?: string;
  related_todo_id?: string;
  related_conversation_id?: string;
  tags: string[];
  category?: string;
  total_executions: number;
  successful_executions: number;
  last_execution_at?: string;
  average_execution_time?: number;
}

// Community workflow step (simplified)
export interface CommunityWorkflowStep {
  title: string;
  tool_name: string;
  tool_category: string;
  description: string;
}

// Community workflow data
export interface CommunityWorkflow {
  id: string;
  title: string;
  description: string;
  steps: CommunityWorkflowStep[];
  upvotes: number;
  is_upvoted: boolean;
  created_at: string;
  creator: {
    id: string;
    name: string;
    avatar?: string;
  };
}

// Community workflows response
export interface CommunityWorkflowsResponse {
  workflows: CommunityWorkflow[];
  total: number;
}

// Complete workflow entity
export interface Workflow {
  id: string;
  title: string;
  description: string;
  steps: WorkflowStepType[];
  trigger_config: TriggerConfig;
  execution_config: ExecutionConfig;
  metadata: WorkflowMetadata;
  activated: boolean;
  user_id: string;
  created_at: string;
  updated_at: string;
  last_executed_at?: string;
  current_step_index: number;
  execution_logs: string[];
  error_message?: string;

  // Execution statistics
  total_executions: number;
  successful_executions: number;

  // Community features
  is_public?: boolean;
  created_by?: string;
  upvotes?: number;
  upvoted_by?: string[];
}

// API request types
export interface CreateWorkflowRequest {
  title: string;
  description: string;
  trigger_config: TriggerConfig;
  execution_config?: ExecutionConfig;
  metadata?: Partial<WorkflowMetadata>;
  generate_immediately?: boolean;
}

export interface WorkflowExecutionRequest {
  execution_method?: "chat" | "background" | "hybrid";
  context?: Record<string, unknown>;
}

// API response types
export interface WorkflowStatusResponse {
  workflow_id: string;
  activated: boolean;
  current_step_index: number;
  total_steps: number;
  progress_percentage: number;
  last_updated: string;
  error_message?: string;
  logs: string[];
}

export interface WorkflowListResponse {
  workflows: Workflow[];
  total_count: number;
  page: number;
  page_size: number;
}

export interface WorkflowResponse {
  workflow: Workflow;
  message: string;
}

export interface WorkflowExecutionResponse {
  execution_id: string;
  message: string;
  estimated_completion_time?: string;
}
