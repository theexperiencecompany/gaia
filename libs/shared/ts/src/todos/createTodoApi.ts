import { buildQueryString } from "../api/queryBuilder";
import { normalizeListResponse } from "../api/responseNormalizer";
import { TODO_ENDPOINTS } from "../api/todosApi";
import type {
  BulkMoveRequest,
  Priority,
  Project,
  ProjectCreate,
  ProjectUpdate,
  SubTask,
  Todo,
  TodoCounts,
  TodoLabel,
  TodoListResponse,
} from "../types/todo";
import type {
  SemanticSearchOptions,
  TodoApiClient,
  WorkflowGenerateResult,
  WorkflowStatusResult,
} from "./apiClient";

/**
 * Per-call options forwarded to the platform HTTP adapter. Mirrors the
 * shape both web (axios+toast) and mobile (fetch) already accept.
 */
export interface RequestOptions {
  silent?: boolean;
  successMessage?: string;
  errorMessage?: string;
}

export interface HttpAdapter {
  get: <T = unknown>(url: string, options?: RequestOptions) => Promise<T>;
  post: <T = unknown>(
    url: string,
    data?: unknown,
    options?: RequestOptions,
  ) => Promise<T>;
  put: <T = unknown>(
    url: string,
    data?: unknown,
    options?: RequestOptions,
  ) => Promise<T>;
  patch: <T = unknown>(
    url: string,
    data?: unknown,
    options?: RequestOptions,
  ) => Promise<T>;
  delete: <T = unknown>(
    url: string,
    data?: unknown,
    options?: RequestOptions,
  ) => Promise<T>;
}

function unwrapBulkResponse(response: { updated: Todo[] } | Todo[]): Todo[] {
  if (
    typeof response === "object" &&
    response !== null &&
    "updated" in response &&
    Array.isArray(response.updated)
  ) {
    return response.updated;
  }
  return response as Todo[];
}

/**
 * Build a `TodoApiClient` backed by a platform-specific HTTP adapter.
 *
 * Centralizes URL construction, query-string serialization, and response
 * normalization so each app only owns its own auth/transport layer.
 */
export function createTodoApi(http: HttpAdapter): TodoApiClient {
  return {
    getAllTodos: async (filters) => {
      const qs = buildQueryString(
        filters as Record<string, string | number | boolean | null | undefined>,
      );
      const response = await http.get<TodoListResponse | Todo[]>(
        `${TODO_ENDPOINTS.list}${qs}`,
        { silent: true },
      );
      return normalizeListResponse(response);
    },

    getTodo: (todoId) =>
      http.get<Todo>(TODO_ENDPOINTS.get(todoId), {
        silent: true,
        errorMessage: "Failed to fetch task",
      }),

    createTodo: (todo) =>
      http.post<Todo>(TODO_ENDPOINTS.create, todo, {
        errorMessage: "Failed to create task",
      }),

    updateTodo: (todoId, update) =>
      http.put<Todo>(TODO_ENDPOINTS.update(todoId), update),

    deleteTodo: (todoId) =>
      http.delete<void>(TODO_ENDPOINTS.delete(todoId), undefined, {
        errorMessage: "Failed to delete task",
      }),

    getTodoCounts: () =>
      http.get<TodoCounts>(TODO_ENDPOINTS.counts, { silent: true }),

    getAllLabels: async () => {
      try {
        return await http.get<TodoLabel[]>(TODO_ENDPOINTS.labels, {
          silent: true,
        });
      } catch {
        return [];
      }
    },

    getTodosByLabel: async (label, skip, limit) => {
      const params: Record<string, string | number> = { labels: label };
      if (skip !== undefined && limit !== undefined) {
        params.page = Math.floor(skip / limit) + 1;
        params.per_page = limit;
      }
      const response = await http.get<TodoListResponse | Todo[]>(
        `${TODO_ENDPOINTS.list}${buildQueryString(params)}`,
        { silent: true },
      );
      return normalizeListResponse(response);
    },

    searchTodos: async (query) => {
      const response = await http.get<TodoListResponse | Todo[]>(
        `${TODO_ENDPOINTS.list}${buildQueryString({ q: query })}`,
        { silent: true },
      );
      return normalizeListResponse(response);
    },

    semanticSearchTodos: async (query, options: SemanticSearchOptions = {}) => {
      const params: Record<string, string | number | boolean> = {
        q: query,
        mode: "semantic",
      };
      if (options.limit !== undefined) params.per_page = options.limit;
      if (options.project_id) params.project_id = options.project_id;
      if (options.completed !== undefined) params.completed = options.completed;
      if (options.priority) params.priority = options.priority;
      const response = await http.get<TodoListResponse | Todo[]>(
        `${TODO_ENDPOINTS.list}${buildQueryString(params)}`,
        { silent: true },
      );
      return normalizeListResponse(response);
    },

    bulkCompleteTodos: async (todoIds) => {
      const response = await http.post<{ updated: Todo[] } | Todo[]>(
        TODO_ENDPOINTS.bulkComplete,
        todoIds,
        {
          successMessage: `${todoIds.length} tasks completed`,
          errorMessage: "Failed to complete tasks",
        },
      );
      return unwrapBulkResponse(response);
    },

    bulkDeleteTodos: (todoIds) =>
      http.delete<void>(TODO_ENDPOINTS.bulkDelete, todoIds, {
        successMessage: `${todoIds.length} tasks deleted`,
        errorMessage: "Failed to delete tasks",
      }),

    bulkMoveTodos: async (request: BulkMoveRequest) => {
      const response = await http.post<{ updated: Todo[] } | Todo[]>(
        TODO_ENDPOINTS.bulkMove,
        request,
        {
          successMessage: `${request.todo_ids.length} tasks moved`,
          errorMessage: "Failed to move tasks",
        },
      );
      return unwrapBulkResponse(response);
    },

    bulkUpdatePriority: async (todoIds, priority: Priority) => {
      await http.post<unknown>(TODO_ENDPOINTS.bulkPriority, {
        todo_ids: todoIds,
        priority,
      });
    },

    bulkMoveToProject: async (todoIds, projectId) => {
      await http.post<unknown>(TODO_ENDPOINTS.bulkProject, {
        todo_ids: todoIds,
        project_id: projectId,
      });
    },

    addSubtask: async (todoId, title) => {
      await http.post<unknown>(TODO_ENDPOINTS.subtasks(todoId), { title });
    },

    toggleSubtask: (todoId, subtaskId, completed) =>
      http.patch<SubTask>(TODO_ENDPOINTS.subtask(todoId, subtaskId), {
        completed,
      }),

    deleteSubtask: (todoId, subtaskId) =>
      http.delete<void>(TODO_ENDPOINTS.subtask(todoId, subtaskId)),

    getAllProjects: () =>
      http.get<Project[]>(TODO_ENDPOINTS.projects, {
        errorMessage: "Failed to fetch projects",
      }),

    createProject: (project: ProjectCreate) =>
      http.post<Project>(TODO_ENDPOINTS.projects, project, {
        errorMessage: "Failed to create project",
      }),

    updateProject: (projectId, update: ProjectUpdate) =>
      http.put<Project>(TODO_ENDPOINTS.project(projectId), update, {
        errorMessage: "Failed to update project",
        silent: true,
      }),

    deleteProject: (projectId) =>
      http.delete<void>(TODO_ENDPOINTS.project(projectId), undefined, {
        errorMessage: "Failed to delete project",
        silent: true,
      }),

    generateWorkflow: (todoId): Promise<WorkflowGenerateResult> =>
      http.post<WorkflowGenerateResult>(
        TODO_ENDPOINTS.workflow(todoId),
        {},
        { errorMessage: "Failed to generate workflow", silent: true },
      ),

    getWorkflowStatus: (todoId): Promise<WorkflowStatusResult> =>
      http.get<WorkflowStatusResult>(TODO_ENDPOINTS.workflowStatus(todoId), {
        silent: true,
      }),
  } satisfies TodoApiClient;
}
