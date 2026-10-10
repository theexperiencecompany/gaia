import { Priority, type Todo } from "@/types/features/todoTypes";

/** A tracked todo (it has a canvas); pass vfs_path: null for a classic one. */
export function makeTodo(id: string, overrides: Partial<Todo> = {}): Todo {
  return {
    id,
    user_id: "user-1",
    title: `Todo ${id}`,
    description: null,
    labels: [],
    due_date: null,
    due_date_timezone: null,
    priority: Priority.NONE,
    project_id: "project-1",
    completed: false,
    completed_at: null,
    notify_on_run: true,
    subtasks: [],
    workflow_id: null,
    vfs_path: `/todos/${id}/canvas.md`,
    scheduled_at: null,
    recurrence: null,
    expires_at: null,
    references: [],
    workflow_categories: [],
    trigger_subscriptions: [],
    gaia_retry_count: 0,
    pending_approval: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
