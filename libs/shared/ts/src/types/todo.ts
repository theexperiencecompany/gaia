export enum Priority {
  HIGH = "high",
  MEDIUM = "medium",
  LOW = "low",
  NONE = "none",
}

export interface SubTask {
  id: string;
  title: string;
  completed: boolean;
  created_at: string;
}

export interface Todo {
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
  vfs_path?: string;
  scheduled_at?: string | null; // ISO datetime string
  recurrence?: string | null; // 'daily' | 'weekly' | 'every_4h' | cron expression
  expires_at?: string | null; // ISO datetime — when this task becomes irrelevant
  references?: string[]; // IDs of related past tracked todos
  workflow_categories?: string[];
  starred?: boolean;
  created_at: string;
  updated_at: string;
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
  scheduled_at?: string | null;
  recurrence?: string | null;
  expires_at?: string | null;
}

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
  search?: string;
  priority_filter?: string;
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
}

export enum WorkflowStatus {
  NOT_STARTED = "not_started",
  GENERATING = "generating",
  COMPLETED = "completed",
  FAILED = "failed",
}

export interface TodoCounts {
  inbox: number;
  today: number;
  upcoming: number;
  completed: number;
  overdue: number;
}

export interface TodoCreate {
  title: string;
  description?: string;
  labels?: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority?: Priority;
  project_id?: string;
  subtasks?: SubTask[];
  scheduled_at?: string | null;
  recurrence?: string | null;
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

export interface BulkMoveRequest {
  todo_ids: string[];
  project_id: string;
}

export interface TodoLabel {
  name: string;
  count: number;
}
