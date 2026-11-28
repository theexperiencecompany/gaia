/**
 * Shared todos API contract.
 * Defines the endpoint paths every platform's HTTP client calls.
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
  bulkPriority: "/todos/bulk/priority",
  bulkProject: "/todos/bulk/project",
  labels: "/todos/labels",
  canvas: (todoId: string) => `/todos/${todoId}/canvas`,
  conversation: (todoId: string) => `/todos/${todoId}/conversation`,
  subtasks: (todoId: string) => `/todos/${todoId}/subtasks`,
  subtask: (todoId: string, subtaskId: string) =>
    `/todos/${todoId}/subtasks/${subtaskId}`,
  workflow: (todoId: string) => `/todos/${todoId}/workflow`,
  workflowStatus: (todoId: string) => `/todos/${todoId}/workflow-status`,
  projects: "/projects",
  project: (id: string) => `/projects/${id}`,
} as const;
