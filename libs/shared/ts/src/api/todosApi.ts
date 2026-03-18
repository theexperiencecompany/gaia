/**
 * Shared todos API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

export const TODO_ENDPOINTS = {
  list: "/todos",
  create: "/todos",
  get: (id: string) => `/todos/${id}`,
  update: (id: string) => `/todos/${id}`,
  delete: (id: string) => `/todos/${id}`,
  counts: "/todos/counts",
  search: "/todos",
  bulkComplete: "/todos/bulk/complete",
  bulkDelete: "/todos/bulk",
  bulkMove: "/todos/bulk/move",
  subtasks: (todoId: string) => `/todos/${todoId}/subtasks`,
  subtask: (todoId: string, subtaskId: string) =>
    `/todos/${todoId}/subtasks/${subtaskId}`,
  workflow: (todoId: string) => `/todos/${todoId}/workflow`,
  workflowStatus: (todoId: string) => `/todos/${todoId}/workflow-status`,
  projects: "/projects",
  project: (id: string) => `/projects/${id}`,
} as const;

export interface TodoListParams {
  project_id?: string;
  completed?: boolean;
  priority?: string;
  has_due_date?: boolean;
  overdue?: boolean;
  skip?: number;
  limit?: number;
  labels?: string[];
  due_today?: boolean;
  due_this_week?: boolean;
  due_after?: string;
  due_before?: string;
  search?: string;
  priority_filter?: string;
  q?: string;
  mode?: string;
  per_page?: number;
  page?: number;
}

export interface TodoBulkActionParams {
  todo_ids: string[];
}

export interface TodoBulkMoveParams {
  todo_ids: string[];
  project_id: string;
}

export interface SubtaskCreateParams {
  title: string;
}

export interface SubtaskUpdateParams {
  completed: boolean;
}

export interface TodoSemanticSearchParams {
  q: string;
  mode?: "semantic" | "keyword";
  per_page?: number;
  project_id?: string;
  completed?: boolean;
  priority?: string;
}
