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

export type TodoFacet = "deliverable" | "notes" | "log";

export const getTodoCanvas = async (
  todoId: string,
): Promise<{ content: string }> =>
  apiService.get<{ content: string }>(TODO_ENDPOINTS.canvas(todoId), {
    silent: true,
  });

/**
 * Reads one facet of a tracked todo. Approval previews MUST read
 * `deliverable` — that is the exact content Approve releases, not GAIA's
 * working memory.
 */
export const getTodoFacet = async (
  todoId: string,
  facet: TodoFacet,
): Promise<{ content: string }> =>
  apiService.get<{ content: string }>(TODO_ENDPOINTS.facet(todoId, facet), {
    silent: true,
  });
