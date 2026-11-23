/**
 * Server payloads shaped by the generated API models, so a bot test feeds the
 * code under test exactly what the API sends.
 */
import type {
  TodoResponse,
  WorkflowWithIntegrations,
} from "@gaia/shared/api/generated";

export function serverWorkflow(
  overrides: Partial<WorkflowWithIntegrations> = {},
): WorkflowWithIntegrations {
  return {
    activated: true,
    created_at: "2026-11-01T09:00:00Z",
    created_by: null,
    creator: null,
    current_step_index: 0,
    deactivated_reason: null,
    description: "Summarises the inbox every morning",
    error_message: null,
    execution_logs: [],
    gate: null,
    icon: null,
    icon_color: null,
    id: "wf-1",
    integration_ids: [],
    is_explore: false,
    is_public: false,
    is_system_workflow: false,
    is_todo_workflow: false,
    last_executed_at: null,
    max_occurrences: null,
    missing_integrations: null,
    notify_on_completion: true,
    occurrence_count: 0,
    prompt: "Summarise my inbox",
    repeat: null,
    required_integrations: null,
    scheduled_at: null,
    slug: null,
    source_integration: null,
    source_todo_id: null,
    status: "scheduled",
    steps: [],
    stop_after: null,
    successful_executions: 0,
    system_workflow_key: null,
    title: "Morning brief",
    total_executions: 0,
    trigger_config: { type: "manual", enabled: true },
    updated_at: null,
    user_id: "user-1",
    ...overrides,
  };
}

export function serverTodo(
  overrides: Partial<TodoResponse> = {},
): TodoResponse {
  return {
    completed: false,
    completed_at: null,
    created_at: "2026-11-01T09:00:00Z",
    description: null,
    due_date: null,
    due_date_timezone: null,
    expires_at: null,
    gaia_retry_count: 0,
    id: "t-1",
    labels: [],
    notify_on_run: false,
    parent_todo_id: null,
    pending_approval: null,
    priority: "none",
    project_id: null,
    recurrence: null,
    references: [],
    scheduled_at: null,
    sub_todo_count: 0,
    subtasks: [],
    title: "Buy milk",
    trigger_subscriptions: [],
    updated_at: "2026-11-01T09:00:00Z",
    user_id: "user-1",
    vfs_path: null,
    workflow_categories: [],
    workflow_id: null,
    ...overrides,
  };
}
