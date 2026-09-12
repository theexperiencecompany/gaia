import { TODO_ENDPOINTS } from "@shared/api/todosApi";
import { createTodoApi, type HttpAdapter } from "@shared/todos";
import { apiService } from "@/lib/api/service";

const httpAdapter: HttpAdapter = {
  get: (url, options) => apiService.get(url, options),
  post: (url, data, options) => apiService.post(url, data, options),
  put: (url, data, options) => apiService.put(url, data, options),
  patch: (url, data, options) => apiService.patch(url, data, options),
  delete: (url, data, options) => apiService.delete(url, data, options),
};

export const todoApi = createTodoApi(httpAdapter);

export interface TodoNotes {
  /** canvas.md: the recall doc (Key Details / Current State / Context / Learnings). */
  content: string;
  /** activity.md: the dated log, oldest first. */
  activity: string;
}

export const getTodoCanvas = async (todoId: string): Promise<TodoNotes> =>
  apiService.get<TodoNotes>(TODO_ENDPOINTS.canvas(todoId), {
    silent: true,
  });
