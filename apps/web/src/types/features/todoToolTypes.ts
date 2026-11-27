import type {
  ProjectResponse,
  TodoResponse,
  TodoStats,
} from "@shared/api/generated";

export type TodoAction =
  | "list"
  | "create"
  | "update"
  | "delete"
  | "search"
  | "stats";

/** The todo_data card: todo_tool.py streams serialized TodoResponse / ProjectResponse / TodoStats models. */
export interface TodoToolData {
  todos?: TodoResponse[];
  projects?: ProjectResponse[];
  stats?: TodoStats;
  action?: TodoAction;
  message?: string;
}
