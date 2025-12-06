export enum Priority {
  HIGH = "high",
  MEDIUM = "medium",
  LOW = "low",
  NONE = "none",
}

export enum WorkflowStatus {
  NOT_STARTED = "not_started",
  GENERATING = "generating",
  COMPLETED = "completed",
  FAILED = "failed",
}

export interface SubTask {
  id: string;
  title: string;
  completed: boolean;
  created_at: string;
}

export interface Todo extends Record<string, unknown> {
  id: string;
  user_id: string;
  title: string;
  description?: string;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority: Priority;
  project_id: string;
  completed: boolean;
  subtasks: SubTask[];
  workflow_id?: string;
  created_at: string;
  updated_at: string;
}

export interface TodoCreate extends Record<string, unknown> {
  title: string;
  description?: string;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority: Priority;
  project_id?: string;
  subtasks?: SubTask[];
}

export interface TodoUpdate {
  title?: string;
  description?: string;
  labels?: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority?: Priority;
  project_id?: string;
  completed?: boolean;
  subtasks?: SubTask[];
  workflow_id?: string;
}

export interface Project {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  color?: string;
  is_default: boolean;
  todo_count: number;
  created_at: string;
  updated_at: string;
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

// Filter types for todos
export interface TodoFilters {
  project_id?: string;
  completed?: boolean;
  priority?: Priority;
  has_due_date?: boolean;
  overdue?: boolean;
  skip?: number;
  limit?: number;
  labels?: string[];
  due_today?: boolean;
  due_this_week?: boolean;
  due_after?: string;
  due_before?: string;
}

// Stats response type
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

// Bulk operation types
export interface BulkMoveRequest {
  todo_ids: string[];
  project_id: string;
}

// New API response types
export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  pages: number;
  has_next: boolean;
  has_prev: boolean;
}

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
