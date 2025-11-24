// todo Tool Types for AI Assistant Integration

import type { Priority } from "./todoTypes";
import type { Workflow } from "./workflowTypes";

export interface TodoToolData {
  todos?: TodoItem[];
  projects?: TodoProject[];
  stats?: TodoToolStats;
  action?: TodoAction;
  message?: string;
}

export type TodoAction =
  | "list"
  | "create"
  | "update"
  | "delete"
  | "search"
  | "stats";

export interface TodoItem {
  id: string;
  title: string;
  description?: string;
  completed: boolean;
  priority: Priority;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  project_id?: string;
  project?: TodoProject;
  subtasks: TodoSubtask[];
  created_at: string;
  updated_at: string;
  workflow?: Workflow;
}

export interface TodoSubtask {
  id: string;
  title: string;
  completed: boolean;
}

export interface TodoProject {
  id: string;
  name: string;
  description?: string;
  color?: string;
  is_default?: boolean;
  todo_count?: number;
  completion_percentage?: number;
}

export interface TodoToolStats {
  total: number;
  completed: number;
  pending: number;
  overdue: number;
  today: number;
  upcoming: number;
}
