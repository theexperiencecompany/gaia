import { create } from "zustand";
import { devtools } from "zustand/middleware";

import { todoApi } from "@/features/todo/api/todoApi";
import { startWorkflowPolling } from "@/features/todo/hooks/useTodoWorkflowGlobalListener";
import { toast } from "@/lib/toast";
import type {
  Project,
  Todo,
  TodoCreate,
  TodoFilters,
  TodoUpdate,
} from "@/types/features/todoTypes";
import type { Workflow } from "@/types/features/workflowTypes";

interface CachedWorkflowStatus {
  has_workflow: boolean;
  is_generating: boolean;
  workflow: Workflow | null;
  cachedAt: number;
}

interface TodoCounts {
  inbox: number;
  today: number;
  upcoming: number;
  completed: number;
  overdue: number;
}

interface TodoState {
  todos: Todo[];
  projects: Project[];
  labels: { name: string; count: number }[];
  counts: TodoCounts;
  loading: boolean;
  initialLoading: boolean;
  error: string | null;
  workflowStatusCache: Record<string, CachedWorkflowStatus>;
}

interface TodoActions {
  setTodos: (todos: Todo[]) => void;
  setProjects: (projects: Project[]) => void;
  setLabels: (labels: { name: string; count: number }[]) => void;
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
  loadLabels: () => Promise<void>;
  loadCounts: () => Promise<void>;
  refreshAll: () => Promise<void>;
  prefetchWorkflowStatus: (todoId: string) => Promise<void>;
}

type TodoStore = TodoState & TodoActions;

const initialState: TodoState = {
  todos: [],
  projects: [],
  labels: [],
  counts: {
    inbox: 0,
    today: 0,
    upcoming: 0,
    completed: 0,
    overdue: 0,
  },
  loading: false,
  initialLoading: true,
  error: null,
  workflowStatusCache: {},
};

export const useTodoStore = create<TodoStore>()(
  devtools(
    (set, get) => ({
      ...initialState,

      setTodos: (todos) => set({ todos }, false, "setTodos"),
      setProjects: (projects) => set({ projects }, false, "setProjects"),
      setLabels: (labels) => set({ labels }, false, "setLabels"),
      setCounts: (counts) => set({ counts }, false, "setCounts"),
      setLoading: (loading) => set({ loading }, false, "setLoading"),
      setError: (error) => set({ error }, false, "setError"),

      addTodo: (todo) =>
        set((state) => ({ todos: [todo, ...state.todos] }), false, "addTodo"),

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
        set({ loading: true, error: null });
        try {
          const fetchedTodos = await todoApi.getAllTodos(filters);
          set({ todos: fetchedTodos, loading: false, initialLoading: false });
        } catch (err) {
          const error =
            err instanceof Error ? err.message : "Failed to load todos";
          set({ error, loading: false, initialLoading: false });
          console.error("Failed to load todos:", err);
        }
      },

      createTodo: async (todoData) => {
        set({ error: null });

        // Build optimistic todo with a temp ID so it appears in the list immediately
        const tempId = `optimistic-${Date.now()}`;
        const now = new Date().toISOString();
        const optimisticTodo: Todo = {
          id: tempId,
          user_id: "",
          title: todoData.title,
          description: todoData.description,
          labels: todoData.labels,
          due_date: todoData.due_date,
          due_date_timezone: todoData.due_date_timezone,
          priority: todoData.priority,
          project_id: todoData.project_id ?? "",
          completed: false,
          subtasks: todoData.subtasks ?? [],
          created_at: now,
          updated_at: now,
        };

        // Add immediately — modal can close before the API responds
        get().addTodo(optimisticTodo);

        // Fire API in background; replace or rollback when it settles
        todoApi
          .createTodo(todoData)
          .then((newTodo) => {
            get().replaceTodo(tempId, newTodo);
            get().loadCounts().catch(console.error);
            toast.info("Generating workflow...");
            // Poll for workflow completion as fallback (WS may not deliver from ARQ worker)
            startWorkflowPolling(newTodo.id);
          })
          .catch((err) => {
            get().removeTodo(tempId);
            const error =
              err instanceof Error ? err.message : "Failed to create task";
            set({ error });
            toast.error(error);
          });

        return optimisticTodo;
      },

      updateTodo: async (todoId, updates) => {
        set({ error: null });

        // Get current todo for rollback
        const currentTodo = get().todos.find((t) => t.id === todoId);
        if (!currentTodo) throw new Error("Todo not found");

        // Optimistic update
        get().updateTodoOptimistic(todoId, updates as Partial<Todo>);

        try {
          const updatedTodo = await todoApi.updateTodo(todoId, updates);

          // Update with server response
          get().updateTodoOptimistic(todoId, updatedTodo);

          // Refresh counts in background
          get().loadCounts().catch(console.error);

          return updatedTodo;
        } catch (err) {
          // Rollback on error
          get().updateTodoOptimistic(todoId, currentTodo);

          const error =
            err instanceof Error ? err.message : "Failed to update todo";
          set({ error });
          throw err;
        }
      },

      deleteTodo: async (todoId) => {
        set({ error: null });

        // Get current todo for rollback
        const currentTodo = get().todos.find((t) => t.id === todoId);
        if (!currentTodo) throw new Error("Todo not found");

        // Optimistic removal
        get().removeTodo(todoId);

        try {
          await todoApi.deleteTodo(todoId);

          // Refresh counts in background
          get().loadCounts().catch(console.error);
        } catch (err) {
          // Rollback on error
          get().addTodo(currentTodo);

          const error =
            err instanceof Error ? err.message : "Failed to delete todo";
          set({ error });
          throw err;
        }
      },

      loadProjects: async () => {
        try {
          const fetchedProjects = await todoApi.getAllProjects();
          set({ projects: fetchedProjects });
        } catch (err) {
          console.error("Failed to load projects:", err);
        }
      },

      loadLabels: async () => {
        try {
          const fetchedLabels = await todoApi.getAllLabels();
          set({ labels: fetchedLabels });
        } catch (err) {
          console.error("Failed to load labels:", err);
        }
      },

      loadCounts: async () => {
        try {
          const fetchedCounts = await todoApi.getTodoCounts();
          set({ counts: fetchedCounts });
        } catch (err) {
          console.error("Failed to load counts:", err);
        }
      },

      refreshAll: async () => {
        const actions = get();
        await Promise.allSettled([
          actions.loadTodos(),
          actions.loadProjects(),
          actions.loadLabels(),
          actions.loadCounts(),
        ]);
      },

      prefetchWorkflowStatus: async (todoId) => {
        // Skip optimistic todos — they don't exist on the server yet
        if (todoId.startsWith("optimistic-")) return;
        const CACHE_TTL_MS = 30_000; // 30 seconds
        const existing = get().workflowStatusCache[todoId];
        if (existing && Date.now() - existing.cachedAt < CACHE_TTL_MS) return;
        try {
          const status = await todoApi.getWorkflowStatus(todoId);
          set(
            (state) => ({
              workflowStatusCache: {
                ...state.workflowStatusCache,
                [todoId]: {
                  has_workflow: status.has_workflow,
                  is_generating: status.is_generating,
                  workflow: status.workflow,
                  cachedAt: Date.now(),
                },
              },
            }),
            false,
            "prefetchWorkflowStatus",
          );
        } catch {
          // Silently ignore prefetch errors
        }
      },
    }),
    { name: "todo-store" },
  ),
);

// Selectors
export const useTodos = () => useTodoStore((state) => state.todos);
export const useTodoProjects = () => useTodoStore((state) => state.projects);
export const useTodoLabels = () => useTodoStore((state) => state.labels);
export const useTodoCounts = () => useTodoStore((state) => state.counts);
export const useTodoLoading = () => useTodoStore((state) => state.loading);
export const useTodoError = () => useTodoStore((state) => state.error);
