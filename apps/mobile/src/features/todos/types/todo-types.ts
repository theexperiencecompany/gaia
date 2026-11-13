export type { TodoCounts } from "@gaia/shared/api/generated";

import type { SubTask, Todo } from "@gaia/shared/types";
import { Priority } from "@gaia/shared/types";

export type {
  PaginationMeta,
  Project,
  SubTask,
  Todo,
  TodoFilters,
  TodoListResponse,
  TodoUpdate,
} from "@gaia/shared/types";
export { Priority };

/** What a todo row's overflow menu can do, on either platform's menu. */
export interface TodoRowMenuActions {
  onEdit: (todo: Todo) => void;
  onSnooze: (todo: Todo) => void;
  onDelete: (todo: Todo) => void;
  onOpenMenu: (todo: Todo) => void;
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

export type FilterTab =
  | "all"
  | "today"
  | "upcoming"
  | "inbox"
  | "overdue"
  | "completed";

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
