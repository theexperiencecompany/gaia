import type {
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

export interface ContentCreator {
  id: string;
  name: string;
  avatar?: string;
}

export type WorkflowStep = WorkflowStepOutput;

export type Workflow = WorkflowWithIntegrations;

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
