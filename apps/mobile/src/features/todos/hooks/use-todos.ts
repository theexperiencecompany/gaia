import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import { useTodoStore } from "../store/todo-store";
import type {
  FilterTab,
  Priority,
  Todo,
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

function getFiltersForTab(tab: FilterTab): TodoFilters {
  switch (tab) {
    case "today":
      return { due_today: true, completed: false };
    case "upcoming":
      return { due_this_week: true, completed: false };
    case "overdue":
      return { overdue: true, completed: false };
    case "inbox":
      return { completed: false };
    case "completed":
      return { completed: true };
    default:
      return {};
  }
}

/**
 * React hook over the shared todo store, scoped by mobile filter tabs.
 *
 * The shared store owns todos/projects/counts state + optimistic mutations.
 * This hook composes a TodoFilters payload from the local `activeFilter` + the
 * caller's options, calls `loadTodos`/`loadProjects`/`loadCounts` from the
 * store, and re-runs on WebSocket events so screens stay live.
 */
export function useTodos(options: UseTodosOptions = {}) {
  const { search, priority, label, projectId } = options;
  const [activeFilter, setActiveFilterState] = useState<FilterTab>("today");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const {
    todos,
    projects,
    counts,
    loading,
    initialLoading,
    error,
    loadTodos,
    loadProjects,
    loadCounts,
    createTodo: storeCreateTodo,
    updateTodo: storeUpdateTodo,
    deleteTodo: storeDeleteTodo,
  } = useTodoStore(
    useShallow((state) => ({
      todos: state.todos,
      projects: state.projects,
      counts: state.counts,
      loading: state.loading,
      initialLoading: state.initialLoading,
      error: state.error,
      loadTodos: state.loadTodos,
      loadProjects: state.loadProjects,
      loadCounts: state.loadCounts,
      createTodo: state.createTodo,
      updateTodo: state.updateTodo,
      deleteTodo: state.deleteTodo,
    })),
  );

  const filtersKey = useMemo(() => {
    const baseFilters = getFiltersForTab(activeFilter);
    const filters: TodoFilters = {
      ...baseFilters,
      ...(search ? { search } : {}),
      ...(priority ? { priority: priority as Priority } : {}),
      ...(label ? { labels: [label] } : {}),
      ...(projectId ? { project_id: projectId } : {}),
    };
    return JSON.stringify(filters);
  }, [activeFilter, search, priority, label, projectId]);

  const fetchData = useCallback(
    async (refresh = false) => {
      if (refresh) setIsRefreshing(true);
      try {
        const filters = JSON.parse(filtersKey) as TodoFilters;
        await Promise.all([loadTodos(filters), loadProjects(), loadCounts()]);
      } finally {
        if (refresh) setIsRefreshing(false);
      }
    },
    [filtersKey, loadTodos, loadProjects, loadCounts],
  );

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const fetchDataRef = useRef(fetchData);
  fetchDataRef.current = fetchData;

  useEffect(() => {
    const handleEvent = () => {
      void fetchDataRef.current(true);
    };
    const unsubCreated = wsManager.subscribe(
      WS_EVENTS.TODO_CREATED,
      handleEvent,
    );
    const unsubUpdated = wsManager.subscribe(
      WS_EVENTS.TODO_UPDATED,
      handleEvent,
    );
    const unsubDeleted = wsManager.subscribe(
      WS_EVENTS.TODO_DELETED,
      handleEvent,
    );
    return () => {
      unsubCreated();
      unsubUpdated();
      unsubDeleted();
    };
  }, []);

  const setActiveFilter = useCallback((filter: FilterTab) => {
    setActiveFilterState(filter);
  }, []);

  const refetch = useCallback(async () => {
    await fetchData(true);
  }, [fetchData]);

  const createTodo = useCallback(
    async (data: TodoCreate): Promise<Todo> => {
      const newTodo = await storeCreateTodo(data);
      return newTodo;
    },
    [storeCreateTodo],
  );

  const updateTodo = useCallback(
    async (id: string, update: TodoUpdate) => {
      await storeUpdateTodo(id, update);
    },
    [storeUpdateTodo],
  );

  const deleteTodo = useCallback(
    async (id: string) => {
      await storeDeleteTodo(id);
    },
    [storeDeleteTodo],
  );

  const toggleComplete = useCallback(
    async (todo: Todo) => {
      await storeUpdateTodo(todo.id, { completed: !todo.completed });
    },
    [storeUpdateTodo],
  );

  const sortedTodos = useMemo(
    () => [...todos].sort((a, b) => Number(a.completed) - Number(b.completed)),
    [todos],
  );

  return {
    todos: sortedTodos,
    projects,
    counts,
    isLoading: initialLoading || loading,
    isRefreshing,
    error,
    activeFilter,
    setActiveFilter,
    refetch,
    createTodo,
    updateTodo,
    deleteTodo,
    toggleComplete,
  };
}
