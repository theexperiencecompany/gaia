import { apiService } from "@/lib/api";
import type {
  Project,
  Todo,
  TodoCounts,
  TodoCreate,
  TodoFilters,
  TodoListResponse,
  TodoUpdate,
} from "../types/todo-types";

function buildQueryString(filters?: TodoFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(filters)) {
    if (value == null || value === "") continue;

    if (key === "skip" && filters.limit) {
      const page = Math.floor(Number(value) / filters.limit) + 1;
      params.append("page", String(page));
    } else if (key === "limit") {
      params.append("per_page", String(value));
    } else if (key !== "skip") {
      params.append(key, String(value));
    }
  }

  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function extractTodos(response: TodoListResponse | Todo[]): Todo[] {
  if (
    typeof response === "object" &&
    response !== null &&
    "data" in response &&
    Array.isArray(response.data)
  ) {
    return response.data;
  }
  return response as Todo[];
}

export const todoApi = {
  getAllTodos: async (filters?: TodoFilters): Promise<Todo[]> => {
    const response = await apiService.get<TodoListResponse | Todo[]>(
      `/todos${buildQueryString(filters)}`,
    );
    return extractTodos(response);
  },

  getTodo: async (todoId: string): Promise<Todo> => {
    return apiService.get<Todo>(`/todos/${todoId}`);
  },

  createTodo: async (todo: TodoCreate): Promise<Todo> => {
    return apiService.post<Todo>("/todos", todo);
  },

  updateTodo: async (todoId: string, update: TodoUpdate): Promise<Todo> => {
    return apiService.put<Todo>(`/todos/${todoId}`, update);
  },

  deleteTodo: async (todoId: string): Promise<void> => {
    return apiService.delete(`/todos/${todoId}`);
  },

  completeTodo: async (todoId: string): Promise<Todo> => {
    return apiService.put<Todo>(`/todos/${todoId}`, { completed: true });
  },

  uncompleteTodo: async (todoId: string): Promise<Todo> => {
    return apiService.put<Todo>(`/todos/${todoId}`, { completed: false });
  },

  getTodoCounts: async (): Promise<TodoCounts> => {
    return apiService.get<TodoCounts>("/todos/counts");
  },

  getAllProjects: async (): Promise<Project[]> => {
    return apiService.get<Project[]>("/projects");
  },
};
