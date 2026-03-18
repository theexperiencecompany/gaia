import type { SubTask } from "@gaia/shared/types";
import { Priority } from "@gaia/shared/types";

export { Priority };
export type {
  PaginationMeta,
  Project,
  SubTask,
  Todo,
  TodoFilters,
  TodoListResponse,
  TodoUpdate,
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

export interface SortOption {
  field: "created_at" | "due_date" | "priority" | "title";
  direction: "asc" | "desc";
  label: string;
}

export const SORT_OPTIONS: SortOption[] = [
  { field: "created_at", direction: "desc", label: "Newest first" },
  { field: "created_at", direction: "asc", label: "Oldest first" },
  { field: "due_date", direction: "asc", label: "Due date (earliest)" },
  { field: "due_date", direction: "desc", label: "Due date (latest)" },
  { field: "priority", direction: "desc", label: "Priority (high first)" },
  { field: "priority", direction: "asc", label: "Priority (low first)" },
  { field: "title", direction: "asc", label: "Title A–Z" },
  { field: "title", direction: "desc", label: "Title Z–A" },
];
