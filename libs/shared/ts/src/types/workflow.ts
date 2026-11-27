import type {
  PublicWorkflowCard,
  WorkflowCreator,
  WorkflowStepOutput,
  WorkflowWithIntegrations,
} from "../api/generated";

export type {
  TriggerConfig,
  WorkflowListResponse,
  WorkflowResponse,
} from "../api/generated";

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

export type ContentCreator = WorkflowCreator;

export type WorkflowStep = WorkflowStepOutput;

export type Workflow = WorkflowWithIntegrations;

export type CommunityWorkflow = PublicWorkflowCard;
