import { create } from "zustand";
import { devtools } from "zustand/middleware";

import { todoApi } from "@/features/todo/api/todoApi";
import type {
  Project,
  Todo,
  TodoCreate,
  TodoFilters,
  TodoUpdate,
} from "@/types/features/todoTypes";

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
  error: string | null;
}

interface TodoActions {
  setTodos: (todos: Todo[]) => void;
  setProjects: (projects: Project[]) => void;
  setLabels: (labels: { name: string; count: number }[]) => void;
  setCounts: (counts: TodoCounts) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  addTodo: (todo: Todo) => void;
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
  error: null,
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
          set({ todos: fetchedTodos, loading: false });
        } catch (err) {
          const error =
            err instanceof Error ? err.message : "Failed to load todos";
          set({ error, loading: false });
          console.error("Failed to load todos:", err);
        }
      },

      createTodo: async (todoData) => {
        set({ error: null });
        try {
          const newTodo = await todoApi.createTodo(todoData);

          // Optimistically add to current list
          get().addTodo(newTodo);

          // Refresh counts in background
          get().loadCounts().catch(console.error);

          return newTodo;
        } catch (err) {
          const error =
            err instanceof Error ? err.message : "Failed to create todo";
          set({ error });
          throw err;
        }
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
