import { create, type StoreApi, type UseBoundStore } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  Priority,
  Project,
  ProjectCreate,
  ProjectUpdate,
  Todo,
  TodoCounts,
  TodoCreate,
  TodoFilters,
  TodoLabel,
  TodoUpdate,
} from "../types/todo";
import type { TodoApiClient } from "./apiClient";
import {
  buildWorkflowStatusEntry,
  isWorkflowStatusFresh,
  type WorkflowStatusCacheEntry,
} from "./workflowStatus";

export interface NotifyAdapter {
  success?: (message: string) => void;
  error?: (message: string) => void;
  info?: (message: string) => void;
}

export interface CreateTodoStoreOptions {
  notify?: NotifyAdapter;
  /** Called after a real (non-optimistic) todo is persisted. Web uses this
   *  to start the workflow polling fallback. Optional. */
  onTodoCreated?: (todoId: string) => void;
  /** Devtools store name. Defaults to "todo-store". */
  devtoolsName?: string;
}

interface TodoState {
  todos: Todo[];
  projects: Project[];
  labels: TodoLabel[];
  counts: TodoCounts;
  loading: boolean;
  initialLoading: boolean;
  error: string | null;
  workflowStatusCache: Record<string, WorkflowStatusCacheEntry>;
}

interface TodoActions {
  setTodos: (todos: Todo[]) => void;
  setProjects: (projects: Project[]) => void;
  setLabels: (labels: TodoLabel[]) => void;
  setCounts: (counts: TodoCounts) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  addTodo: (todo: Todo) => void;
  replaceTodo: (tempId: string, todo: Todo) => void;
  updateTodoOptimistic: (todoId: string, updates: Partial<Todo>) => void;
  removeTodo: (todoId: string) => void;
  loadTodos: (filters?: TodoFilters) => Promise<void>;
  createTodo: (todoData: TodoCreate) => Promise<Todo>;
  updateTodo: (todoId: string, updates: TodoUpdate) => Promise<Todo>;
  deleteTodo: (todoId: string) => Promise<void>;
  loadProjects: () => Promise<void>;
  createProject: (data: ProjectCreate) => Promise<Project>;
  updateProject: (projectId: string, data: ProjectUpdate) => Promise<Project>;
  deleteProject: (projectId: string) => Promise<void>;
  loadLabels: () => Promise<void>;
  loadCounts: () => Promise<void>;
  refreshCounts: () => Promise<void>;
  refreshAll: (filters?: TodoFilters) => Promise<void>;
  prefetchWorkflowStatus: (todoId: string) => Promise<void>;
  setWorkflowStatusEntry: (
    todoId: string,
    entry: WorkflowStatusCacheEntry,
  ) => void;
  bulkComplete: (todoIds: string[]) => Promise<void>;
  bulkDelete: (todoIds: string[]) => Promise<void>;
  bulkUpdatePriority: (todoIds: string[], priority: Priority) => Promise<void>;
  bulkMoveToProject: (
    todoIds: string[],
    projectId: string | null,
  ) => Promise<void>;
}

export type TodoStore = TodoState & TodoActions;
export type TodoStoreHook = UseBoundStore<StoreApi<TodoStore>>;

const INITIAL_COUNTS: TodoCounts = {
  inbox: 0,
  today: 0,
  upcoming: 0,
  completed: 0,
  overdue: 0,
};

const INITIAL_STATE: TodoState = {
  todos: [],
  projects: [],
  labels: [],
  counts: INITIAL_COUNTS,
  loading: false,
  initialLoading: true,
  error: null,
  workflowStatusCache: {},
};

/**
 * Create a Zustand store bound to a `TodoApiClient`.
 *
 * Both web and mobile call this once at boot with their platform-specific
 * `TodoApiClient`. The returned hook is the single source of truth for todo
 * state across the app.
 */
export function createTodoStore(
  api: TodoApiClient,
  options: CreateTodoStoreOptions = {},
): TodoStoreHook {
  const { notify, onTodoCreated, devtoolsName = "todo-store" } = options;

  return create<TodoStore>()(
    devtools(
      (set, get) => {
        // Monotonic id so a stale list response (slow first load, fast filter
        // change) never overwrites the newer one — last writer wins.
        let loadTodosSeq = 0;
        // Same guard for the totals: a counts read that started before a
        // write must not overwrite the post-write refresh.
        let loadCountsSeq = 0;
        // One in-flight promise per key so components mounting together
        // (list page + sidebar) share a single network request.
        const inFlight = new Map<string, Promise<unknown>>();

        function dedupe<T>(key: string, fn: () => Promise<T>): Promise<T> {
          const existing = inFlight.get(key);
          if (existing) return existing as Promise<T>;
          const p = fn().finally(() => {
            if (inFlight.get(key) === p) inFlight.delete(key);
          });
          inFlight.set(key, p);
          return p;
        }

        return {
          ...INITIAL_STATE,

          setTodos: (todos) => set({ todos }, false, "setTodos"),
          setProjects: (projects) => set({ projects }, false, "setProjects"),
          setLabels: (labels) => set({ labels }, false, "setLabels"),
          setCounts: (counts) => set({ counts }, false, "setCounts"),
          setLoading: (loading) => set({ loading }, false, "setLoading"),
          setError: (error) => set({ error }, false, "setError"),

          addTodo: (todo) =>
            set(
              (state) => ({ todos: [todo, ...state.todos] }),
              false,
              "addTodo",
            ),

          replaceTodo: (tempId, todo) =>
            set(
              (state) => ({
                todos: state.todos.map((t) => (t.id === tempId ? todo : t)),
              }),
              false,
              "replaceTodo",
            ),

          updateTodoOptimistic: (todoId, updates) =>
            set(
              (state) => ({
                todos: state.todos.map((todo) =>
                  todo.id === todoId ? { ...todo, ...updates } : todo,
                ),
              }),
              false,
              "updateTodoOptimistic",
            ),

          removeTodo: (todoId) =>
            set(
              (state) => ({
                todos: state.todos.filter((todo) => todo.id !== todoId),
              }),
              false,
              "removeTodo",
            ),

          loadTodos: async (filters) => {
            const seq = ++loadTodosSeq;
            set({ loading: true, error: null }, false, "loadTodos/start");
            try {
              const key = `todos:${JSON.stringify(filters ?? null)}`;
              const todos = await dedupe(key, () => api.getAllTodos(filters));
              if (seq !== loadTodosSeq) return;
              set(
                { todos, loading: false, initialLoading: false },
                false,
                "loadTodos/success",
              );
            } catch (err) {
              if (seq !== loadTodosSeq) return;
              const error =
                err instanceof Error ? err.message : "Failed to load todos";
              set(
                { error, loading: false, initialLoading: false },
                false,
                "loadTodos/error",
              );
            }
          },

          createTodo: async (todoData) => {
            set({ error: null });
            const tempId = `optimistic-${Date.now()}`;
            const now = new Date().toISOString();
            const optimisticTodo: Todo = {
              id: tempId,
              user_id: "",
              title: todoData.title,
              description: todoData.description ?? null,
              labels: todoData.labels ?? [],
              due_date: todoData.due_date ?? null,
              due_date_timezone: todoData.due_date_timezone ?? null,
              priority: todoData.priority ?? "none",
              project_id: todoData.project_id ?? "",
              completed: false,
              completed_at: null,
              notify_on_run: todoData.notify_on_run ?? true,
              subtasks: (todoData.subtasks ?? []).map((subtask) => ({
                id: subtask.id ?? "",
                title: subtask.title,
                completed: subtask.completed ?? false,
                created_at: subtask.created_at ?? now,
              })),
              workflow_id: null,
              vfs_path: null,
              scheduled_at: todoData.scheduled_at ?? null,
              recurrence: todoData.recurrence ?? null,
              expires_at: null,
              references: [],
              workflow_categories: [],
              trigger_subscriptions: [],
              gaia_retry_count: 0,
              pending_approval: null,
              parent_todo_id: null,
              sub_todo_count: 0,
              created_at: now,
              updated_at: now,
            };

            get().addTodo(optimisticTodo);

            api
              .createTodo(todoData)
              .then((newTodo) => {
                get().replaceTodo(tempId, newTodo);
                get()
                  .refreshCounts()
                  .catch(() => undefined);
                notify?.info?.("Generating workflow...");
                onTodoCreated?.(newTodo.id);
              })
              .catch((err) => {
                get().removeTodo(tempId);
                // Write failures toast but never touch the shared error:
                // that belongs to list loads, whose screen this is not.
                const error =
                  err instanceof Error ? err.message : "Failed to create task";
                notify?.error?.(error);
              });

            return optimisticTodo;
          },

          updateTodo: async (todoId, updates) => {
            set({ error: null });
            const current = get().todos.find((t) => t.id === todoId);
            if (!current) throw new Error("Todo not found");

            get().updateTodoOptimistic(todoId, updates as Partial<Todo>);

            try {
              const updated = await api.updateTodo(todoId, updates);
              get().updateTodoOptimistic(todoId, updated);
              get()
                .refreshCounts()
                .catch(() => undefined);
              return updated;
            } catch (err) {
              get().updateTodoOptimistic(todoId, current);
              // Rolls back and rethrows; the shared error stays a list-load
              // signal so a failed edit never renders as a failed load.
              throw err;
            }
          },

          deleteTodo: async (todoId) => {
            set({ error: null });
            const current = get().todos.find((t) => t.id === todoId);
            if (!current) throw new Error("Todo not found");

            get().removeTodo(todoId);

            try {
              await api.deleteTodo(todoId);
              get()
                .refreshCounts()
                .catch(() => undefined);
            } catch (err) {
              get().addTodo(current);
              // Rolls back and rethrows; the shared error stays a list-load
              // signal so a failed delete never renders as a failed load.
              throw err;
            }
          },

          loadProjects: async () => {
            try {
              const projects = await dedupe("projects", () =>
                api.getAllProjects(),
              );
              set({ projects }, false, "loadProjects");
            } catch {
              // surface via list error UI; project load failures are non-fatal
            }
          },

          createProject: async (data) => {
            const project = await api.createProject(data);
            set(
              (state) => ({ projects: [...state.projects, project] }),
              false,
              "createProject",
            );
            return project;
          },

          updateProject: async (projectId, data) => {
            const updated = await api.updateProject(projectId, data);
            set(
              (state) => ({
                projects: state.projects.map((p) =>
                  p.id === projectId ? updated : p,
                ),
              }),
              false,
              "updateProject",
            );
            return updated;
          },

          deleteProject: async (projectId) => {
            await api.deleteProject(projectId);
            set(
              (state) => ({
                projects: state.projects.filter((p) => p.id !== projectId),
              }),
              false,
              "deleteProject",
            );
          },

          loadLabels: async () => {
            try {
              const labels = await dedupe("labels", () => api.getAllLabels());
              set({ labels }, false, "loadLabels");
            } catch {
              // non-fatal
            }
          },

          loadCounts: async () => {
            const seq = loadCountsSeq;
            try {
              const counts = await dedupe("counts", () => api.getTodoCounts());
              if (seq !== loadCountsSeq) return;
              set({ counts }, false, "loadCounts");
            } catch {
              // non-fatal
            }
          },

          refreshCounts: async () => {
            // Post-write refresh: bypass dedupe so it never joins a read
            // that started before the write, and retire any such read still
            // in flight by moving the generation forward.
            const seq = ++loadCountsSeq;
            try {
              const counts = await api.getTodoCounts();
              if (seq !== loadCountsSeq) return;
              set({ counts }, false, "refreshCounts");
            } catch {
              // non-fatal
            }
          },

          refreshAll: async (filters) => {
            const actions = get();
            await Promise.allSettled([
              actions.loadTodos(filters),
              actions.loadProjects(),
              actions.loadLabels(),
              actions.loadCounts(),
            ]);
          },

          prefetchWorkflowStatus: async (todoId) => {
            if (todoId.startsWith("optimistic-")) return;
            const existing = get().workflowStatusCache[todoId];
            if (isWorkflowStatusFresh(existing)) return;
            try {
              const status = await api.getWorkflowStatus(todoId);
              const entry = buildWorkflowStatusEntry(status);
              set(
                (state) => ({
                  workflowStatusCache: {
                    ...state.workflowStatusCache,
                    [todoId]: entry,
                  },
                }),
                false,
                "prefetchWorkflowStatus",
              );
            } catch {
              // non-fatal
            }
          },

          setWorkflowStatusEntry: (todoId, entry) =>
            set(
              (state) => ({
                workflowStatusCache: {
                  ...state.workflowStatusCache,
                  [todoId]: entry,
                },
              }),
              false,
              "setWorkflowStatusEntry",
            ),

          bulkComplete: async (todoIds) => {
            const updated = await api.bulkCompleteTodos(todoIds);
            const map = new Map(updated.map((t) => [t.id, t]));
            set(
              (state) => ({
                todos: state.todos.map((t) => map.get(t.id) ?? t),
              }),
              false,
              "bulkComplete",
            );
            get()
              .refreshCounts()
              .catch(() => undefined);
          },

          bulkDelete: async (todoIds) => {
            await api.bulkDeleteTodos(todoIds);
            const idSet = new Set(todoIds);
            set(
              (state) => ({
                todos: state.todos.filter((t) => !idSet.has(t.id)),
              }),
              false,
              "bulkDelete",
            );
            get()
              .refreshCounts()
              .catch(() => undefined);
          },

          bulkUpdatePriority: async (todoIds, priority) => {
            await api.bulkUpdatePriority(todoIds, priority);
            const idSet = new Set(todoIds);
            set(
              (state) => ({
                todos: state.todos.map((t) =>
                  idSet.has(t.id) ? { ...t, priority } : t,
                ),
              }),
              false,
              "bulkUpdatePriority",
            );
          },

          bulkMoveToProject: async (todoIds, projectId) => {
            await api.bulkMoveToProject(todoIds, projectId);
            const idSet = new Set(todoIds);
            set(
              (state) => ({
                todos: state.todos.map((t) =>
                  idSet.has(t.id) ? { ...t, project_id: projectId ?? "" } : t,
                ),
              }),
              false,
              "bulkMoveToProject",
            );
            get()
              .refreshCounts()
              .catch(() => undefined);
          },
        };
      },
      { name: devtoolsName },
    ),
  );
}
