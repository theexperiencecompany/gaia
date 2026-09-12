import type { Schema } from "../api/generated";
export type TriggerConfig = Schema<"TriggerConfig">;

export interface ExecutionConfig {
  method: "chat" | "background" | "hybrid";
  timeout_seconds: number;
  max_retries: number;
  retry_delay_seconds: number;
  notify_on_completion: boolean;
  notify_on_failure: boolean;
}

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

export interface ContentCreator {
  id: string;
  name: string;
  avatar?: string;
}

export type WorkflowStep = Schema<"WorkflowStep-Output">;

export type Workflow = Schema<"WorkflowWithIntegrations">;

export interface CommunityWorkflow {
  id: string;
  title: string;
  description: string;
  prompt?: string;
  steps: Omit<WorkflowStep, "id">[];
  created_at: string;
  creator: ContentCreator;
  categories?: string[];
  total_executions?: number;
}

export type WorkflowListResponse = Schema<"WorkflowListResponse">;

export type WorkflowResponse = Schema<"WorkflowResponse">;

export interface CreateWorkflowPayload {
  title: string;
  description?: string;
  prompt: string;
  trigger_config?: Partial<TriggerConfig>;
  steps?: Omit<WorkflowStep, "id">[];
  execution_config?: Partial<ExecutionConfig>;
  metadata?: Partial<WorkflowMetadata>;
  generate_immediately?: boolean;
}
