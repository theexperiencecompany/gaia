export interface TriggerConfig {
  type: string;
  enabled: boolean;
  cron_expression?: string;
  timezone?: string;
  next_run?: string;
  trigger_name?: string;
  integration_id?: string;
  trigger_slug?: string;
  [key: string]: unknown;
}

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

export interface WorkflowStep {
  id: string;
  title: string;
  category: string;
  description: string;
  order?: number;
}

export interface Workflow {
  id: string;
  title: string;
  description: string;
  prompt: string;
  steps: WorkflowStep[];
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
  total_executions: number;
  successful_executions: number;
  is_public?: boolean;
  created_by?: string;
  creator?: ContentCreator;
  is_system_workflow?: boolean;
  source_integration?: string;
  system_workflow_key?: string;
}

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
