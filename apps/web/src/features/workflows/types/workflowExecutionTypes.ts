/**
 * Workflow Execution Types
 *
 * Types for workflow execution history tracking.
 */

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

export interface WorkflowExecutionsResponse {
  executions: WorkflowExecution[];
  total: number;
  has_more: boolean;
}
