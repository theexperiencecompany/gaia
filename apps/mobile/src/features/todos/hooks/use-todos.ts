import { useCallback, useEffect, useMemo, useState } from "react";
import { todoApi } from "../api/todo-api";
import type {
  FilterTab,
  Project,
  Todo,
  TodoCounts,
  TodoCreate,
  TodoFilters,
  TodoUpdate,
} from "../types/todo-types";

interface UseTodosState {
  todos: Todo[];
  projects: Project[];
  counts: TodoCounts | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  activeFilter: FilterTab;
}

interface UseTodosReturn extends UseTodosState {
  setActiveFilter: (filter: FilterTab) => void;
  refetch: () => Promise<void>;
  createTodo: (data: TodoCreate) => Promise<Todo>;
  updateTodo: (id: string, update: TodoUpdate) => Promise<void>;
  deleteTodo: (id: string) => Promise<void>;
  toggleComplete: (todo: Todo) => Promise<void>;
}

function getFiltersForTab(tab: FilterTab): TodoFilters {
  switch (tab) {
    case "today":
      return { due_today: true, completed: false };
    case "upcoming":
      return { due_this_week: true, completed: false };
    case "completed":
      return { completed: true };
    default:
      return { completed: false };
  }
}

export function useTodos(): UseTodosReturn {
  const [state, setState] = useState<UseTodosState>({
    todos: [],
    projects: [],
    counts: null,
    isLoading: true,
    isRefreshing: false,
    error: null,
    activeFilter: "all",
  });

  const fetchData = useCallback(
    async (filter: FilterTab, isRefresh = false) => {
      setState((prev) => ({
        ...prev,
        isLoading: !isRefresh,
        isRefreshing: isRefresh,
        error: null,
      }));

      try {
        const filters = getFiltersForTab(filter);
        const [todos, projects, counts] = await Promise.all([
          todoApi.getAllTodos(filters),
          todoApi.getAllProjects(),
          todoApi.getTodoCounts(),
        ]);

        setState((prev) => ({
          ...prev,
          todos,
          projects,
          counts,
          isLoading: false,
          isRefreshing: false,
        }));
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          isRefreshing: false,
          error: err instanceof Error ? err.message : "Failed to load todos",
        }));
      }
    },
    [],
  );

  useEffect(() => {
    void fetchData(state.activeFilter);
  }, [state.activeFilter, fetchData]);

  const setActiveFilter = useCallback((filter: FilterTab) => {
    setState((prev) => ({ ...prev, activeFilter: filter }));
  }, []);

  const refetch = useCallback(async () => {
    await fetchData(state.activeFilter, true);
  }, [fetchData, state.activeFilter]);

  const createTodo = useCallback(
    async (data: TodoCreate): Promise<Todo> => {
      const newTodo = await todoApi.createTodo(data);
      await fetchData(state.activeFilter, true);
      return newTodo;
    },
    [fetchData, state.activeFilter],
  );

  const updateTodo = useCallback(async (id: string, update: TodoUpdate) => {
    await todoApi.updateTodo(id, update);
    setState((prev) => ({
      ...prev,
      todos: prev.todos.map((t) => (t.id === id ? { ...t, ...update } : t)),
    }));
  }, []);

  const deleteTodo = useCallback(async (id: string) => {
    await todoApi.deleteTodo(id);
    setState((prev) => ({
      ...prev,
      todos: prev.todos.filter((t) => t.id !== id),
    }));
  }, []);

  const toggleComplete = useCallback(async (todo: Todo) => {
    const newCompleted = !todo.completed;
    setState((prev) => ({
      ...prev,
      todos: prev.todos.map((t) =>
        t.id === todo.id ? { ...t, completed: newCompleted } : t,
      ),
    }));

    try {
      await todoApi.updateTodo(todo.id, { completed: newCompleted });
    } catch {
      setState((prev) => ({
        ...prev,
        todos: prev.todos.map((t) =>
          t.id === todo.id ? { ...t, completed: todo.completed } : t,
        ),
      }));
    }
  }, []);

  const sortedTodos = useMemo(() => {
    return [...state.todos].sort(
      (a, b) => Number(a.completed) - Number(b.completed),
    );
  }, [state.todos]);

  return {
    ...state,
    todos: sortedTodos,
    setActiveFilter,
    refetch,
    createTodo,
    updateTodo,
    deleteTodo,
    toggleComplete,
  };
}
