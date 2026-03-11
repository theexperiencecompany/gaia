import type { Priority, SubTask } from "@gaia/shared/types";

export type {
  Priority,
  SubTask,
  Todo,
  TodoUpdate,
  TodoFilters,
  Project,
  PaginationMeta,
  TodoListResponse,
} from "@gaia/shared/types";

export interface Subtask {
  id: string;
  title: string;
  completed: boolean;
}

export interface TodoProject {
  id: string;
  name: string;
  color?: string;
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
}

export interface TodoCounts {
  inbox: number;
  today: number;
  upcoming: number;
  completed: number;
  overdue: number;
}

export type FilterTab = "all" | "today" | "upcoming" | "completed";
