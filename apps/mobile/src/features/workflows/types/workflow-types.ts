import type { WorkflowExecution } from "@gaia/shared/api/generated";

export type {
  WorkflowExecution,
  WorkflowExecutionResponse,
} from "@gaia/shared/api/generated";

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
