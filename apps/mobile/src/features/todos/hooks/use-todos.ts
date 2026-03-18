import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import { todoApi } from "../api/todo-api";
import type {
  FilterTab,
  Priority,
  Project,
  Todo,
  TodoCounts,
  TodoCreate,
  TodoFilters,
  TodoUpdate,
} from "../types/todo-types";

interface UseTodosOptions {
  search?: string;
  priority?: string;
  label?: string;
  projectId?: string;
}

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

export function useTodos(options: UseTodosOptions = {}): UseTodosReturn {
  const { search, priority, label, projectId } = options;

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
        const baseFilters = getFiltersForTab(filter);
        const filters: TodoFilters = {
          ...baseFilters,
          ...(search ? { search } : {}),
          ...(priority ? { priority: priority as Priority } : {}),
          ...(label ? { labels: [label] } : {}),
          ...(projectId ? { project_id: projectId } : {}),
        };
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
    [search, priority, label, projectId],
  );

  useEffect(() => {
    void fetchData(state.activeFilter);
  }, [state.activeFilter, fetchData, search, priority, label, projectId]);

  // Keep a stable ref to the current filter so the WS handler doesn't
  // need to be re-created on every filter change.
  const activeFilterRef = useRef(state.activeFilter);
  useEffect(() => {
    activeFilterRef.current = state.activeFilter;
  }, [state.activeFilter]);

  useEffect(() => {
    const handleTodoEvent = () => {
      void fetchData(activeFilterRef.current, true);
    };

    const unsubCreated = wsManager.subscribe(
      WS_EVENTS.TODO_CREATED,
      handleTodoEvent,
    );
    const unsubUpdated = wsManager.subscribe(
      WS_EVENTS.TODO_UPDATED,
      handleTodoEvent,
    );
    const unsubDeleted = wsManager.subscribe(
      WS_EVENTS.TODO_DELETED,
      handleTodoEvent,
    );

    return () => {
      unsubCreated();
      unsubUpdated();
      unsubDeleted();
    };
  }, [fetchData]);

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
