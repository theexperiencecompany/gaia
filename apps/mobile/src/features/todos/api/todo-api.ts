import { buildQueryString, normalizeListResponse } from "@gaia/shared/api";
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

export const todoApi = {
  getAllTodos: async (filters?: TodoFilters): Promise<Todo[]> => {
    const response = await apiService.get<TodoListResponse | Todo[]>(
      `/todos${buildQueryString(filters as Record<string, string | number | boolean | null | undefined>)}`,
    );
    return normalizeListResponse(response);
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

  bulkComplete: async (todoIds: string[]): Promise<void> => {
    await apiService.post("/todos/bulk/complete", { todo_ids: todoIds });
  },

  bulkDelete: async (todoIds: string[]): Promise<void> => {
    await apiService.delete("/todos/bulk", { todo_ids: todoIds });
  },

  addSubtask: async (todoId: string, title: string): Promise<void> => {
    await apiService.post(`/todos/${todoId}/subtasks`, { title });
  },

  toggleSubtask: async (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ): Promise<void> => {
    await apiService.patch(`/todos/${todoId}/subtasks/${subtaskId}`, {
      completed,
    });
  },

  deleteSubtask: async (todoId: string, subtaskId: string): Promise<void> => {
    await apiService.delete(`/todos/${todoId}/subtasks/${subtaskId}`);
  },
};
