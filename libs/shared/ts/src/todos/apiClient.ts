import type {
  BulkMoveRequest,
  Priority,
  Project,
  ProjectCreate,
  ProjectUpdate,
  SubTask,
  Todo,
  TodoCounts,
  TodoCreate,
  TodoFilters,
  TodoLabel,
  TodoUpdate,
  WorkflowStatus,
} from "../types/todo";
import type { Workflow } from "../types/workflow";

export interface WorkflowGenerateResult {
  status: "generating" | "exists";
  workflow?: Workflow;
  todo_id?: string;
  message: string;
}

export interface WorkflowStatusResult {
  todo_id: string;
  has_workflow: boolean;
  is_generating: boolean;
  workflow_status: WorkflowStatus;
  workflow: Workflow | null;
}

export interface SemanticSearchOptions {
  limit?: number;
  project_id?: string;
  completed?: boolean;
  priority?: string;
}

/**
 * Platform-agnostic contract for the Todos API.
 *
 * Implementations supply the underlying HTTP transport (axios on web with
 * toast/analytics interceptors, fetch on mobile with AsyncStorage auth).
 * The shared store and hooks consume this interface only.
 */
export interface TodoApiClient {
  // Todo CRUD
  getAllTodos: (filters?: TodoFilters) => Promise<Todo[]>;
  getTodo: (todoId: string) => Promise<Todo>;
  createTodo: (todo: TodoCreate) => Promise<Todo>;
  updateTodo: (todoId: string, update: TodoUpdate) => Promise<Todo>;
  deleteTodo: (todoId: string) => Promise<void>;

  // Counts & labels
  getTodoCounts: () => Promise<TodoCounts>;
  getAllLabels: () => Promise<TodoLabel[]>;
  getTodosByLabel: (
    label: string,
    skip?: number,
    limit?: number,
  ) => Promise<Todo[]>;

  // Search
  searchTodos: (query: string) => Promise<Todo[]>;
  semanticSearchTodos: (
    query: string,
    options?: SemanticSearchOptions,
  ) => Promise<Todo[]>;

  // Bulk
  bulkCompleteTodos: (todoIds: string[]) => Promise<Todo[]>;
  bulkDeleteTodos: (todoIds: string[]) => Promise<void>;
  bulkMoveTodos: (request: BulkMoveRequest) => Promise<Todo[]>;
  bulkUpdatePriority: (todoIds: string[], priority: Priority) => Promise<void>;
  bulkMoveToProject: (
    todoIds: string[],
    projectId: string | null,
  ) => Promise<void>;

  // Subtasks
  addSubtask: (todoId: string, title: string) => Promise<void>;
  toggleSubtask: (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ) => Promise<SubTask | void>;
  deleteSubtask: (todoId: string, subtaskId: string) => Promise<void>;

  // Projects
  getAllProjects: () => Promise<Project[]>;
  createProject: (project: ProjectCreate) => Promise<Project>;
  updateProject: (projectId: string, update: ProjectUpdate) => Promise<Project>;
  deleteProject: (projectId: string) => Promise<void>;

  // Workflow
  generateWorkflow: (todoId: string) => Promise<WorkflowGenerateResult>;
  getWorkflowStatus: (todoId: string) => Promise<WorkflowStatusResult>;
}
