import type {
  PaginationMeta as SharedPaginationMeta,
  Priority as SharedPriority,
  SubTask as SharedSubTask,
  Todo as SharedTodo,
} from "@shared/types";

export type {
  PaginationMeta,
  Project,
  SubTask,
  TodoFilters,
  TodoUpdate,
} from "@shared/types";
export { Priority } from "@shared/types";

export enum WorkflowStatus {
  NOT_STARTED = "not_started",
  GENERATING = "generating",
  COMPLETED = "completed",
  FAILED = "failed",
}

// Web version extends shared Todo with Record index signature for table/form usage
export interface Todo extends SharedTodo, Record<string, unknown> {}

export interface TodoCreate extends Record<string, unknown> {
  title: string;
  description?: string;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority: SharedPriority;
  project_id?: string;
  subtasks?: SharedSubTask[];
}

export interface ProjectCreate {
  name: string;
  description?: string;
  color?: string;
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
  color?: string;
}

// Stats response type — web-only advanced feature
export interface TodoStats {
  total: number;
  completed: number;
  pending: number;
  overdue: number;
  by_priority: {
    high: number;
    medium: number;
    low: number;
    none: number;
  };
  by_project: Record<string, number>;
  completion_rate: number;
  labels?: Array<{ name: string; count: number }>;
}

// Bulk operation types — web-only
export interface BulkMoveRequest {
  todo_ids: string[];
  project_id: string;
}

// Web version of TodoListResponse includes optional stats
export interface TodoListResponse {
  data: Todo[];
  meta: SharedPaginationMeta;
  stats?: TodoStats;
}

export enum TodoSearchMode {
  TEXT = "text",
  SEMANTIC = "semantic",
  HYBRID = "hybrid",
}
