import type { PaginationMeta, Todo } from "@shared/types";

export type {
  BulkMoveRequest,
  PaginationMeta,
  Project,
  ProjectCreate,
  ProjectUpdate,
  SubTask,
  Todo,
  TodoCreate,
  TodoFilters,
  TodoUpdate,
} from "@shared/types";
export { Priority, WorkflowStatus } from "@shared/types";

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

// Web version of TodoListResponse includes optional stats
export interface TodoListResponse {
  data: Todo[];
  meta: PaginationMeta;
  stats?: TodoStats;
}

export enum TodoSearchMode {
  TEXT = "text",
  SEMANTIC = "semantic",
  HYBRID = "hybrid",
}
