import type { TriggerConfig, WorkflowStep } from "@gaia/shared/types";

export type {
  CommunityWorkflow,
  ContentCreator,
  CreateWorkflowPayload,
  ExecutionConfig,
  TriggerConfig,
  Workflow,
  WorkflowListResponse,
  WorkflowMetadata,
  WorkflowResponse,
  WorkflowStep,
} from "@gaia/shared/types";

export interface WorkflowExecution {
  execution_id: string;
  workflow_id: string;
  user_id: string;
  status: "running" | "success" | "failed";
  started_at: string;
  completed_at?: string;
  duration_seconds?: number;
  conversation_id?: string;
  summary?: string;
  error_message?: string;
  trigger_type: string;
}

export interface WorkflowExecutionResponse {
  execution_id: string;
  message: string;
  estimated_completion_time?: string;
}

export interface WorkflowExecutionsListResponse {
  executions: WorkflowExecution[];
  total: number;
  has_more: boolean;
}

export interface CommunityWorkflowsResponse {
  workflows: import("@gaia/shared/types").CommunityWorkflow[];
  total: number;
}

export interface UpdateWorkflowPayload {
  title?: string;
  description?: string;
  prompt?: string;
  trigger_config?: Partial<TriggerConfig>;
  steps?: WorkflowStep[];
}

export interface WorkflowStatusResponse {
  workflow_id: string;
  status: string;
  activated: boolean;
  last_execution_at?: string;
  next_run?: string;
}
