"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { useTodoStore } from "@/stores/todoStore";
import type { Priority, TodoFilters } from "@/types/features/todoTypes";

interface UseTodoDataOptions {
  filters?: TodoFilters;
  autoLoad?: boolean;
}

export function useTodoData(options: UseTodoDataOptions = {}) {
  const { filters, autoLoad = true } = options;

  // Use JSON.stringify to create a stable reference for filters
  const filtersString = useMemo(() => JSON.stringify(filters || {}), [filters]);

  const {
    todos: allTodos,
    projects,
    labels,
    counts,
    loading,
    error,
    loadTodos,
    createTodo,
    updateTodo,
    deleteTodo,
    loadProjects,
    loadLabels,
    loadCounts,
    refreshAll,
  } = useTodoStore();

  // Track if initial load has happened
  const hasLoadedRef = useRef(false);

  // Load data on mount if autoLoad is enabled
  useEffect(() => {
    if (autoLoad && !hasLoadedRef.current) {
      hasLoadedRef.current = true;
      const parsedFilters = JSON.parse(filtersString) as TodoFilters;
      loadTodos(parsedFilters);
      loadProjects(); // Load projects so todo chips can display project name/color
      loadCounts(); // Also load counts for dashboard summary
    }
  }, [autoLoad, filtersString, loadTodos, loadCounts, loadProjects]);

  // Refresh function that reloads current filter
  const refresh = useCallback(() => {
    const parsedFilters = JSON.parse(filtersString) as TodoFilters;
    return loadTodos(parsedFilters);
  }, [loadTodos, filtersString]);

  // Convenience methods for specific todo types
  const loadTodayTodos = useCallback(() => {
    return loadTodos({ due_today: true, completed: false });
  }, [loadTodos]);

  const loadUpcomingTodos = useCallback(() => {
    return loadTodos({ due_this_week: true, completed: false });
  }, [loadTodos]);

  const loadCompletedTodos = useCallback(() => {
    return loadTodos({ completed: true });
  }, [loadTodos]);

  const loadTodosByPriority = useCallback(
    (priority: Priority) => {
      return loadTodos({ priority, completed: false });
    },
    [loadTodos],
  );

  const loadTodosByProject = useCallback(
    (projectId: string) => {
      return loadTodos({ project_id: projectId });
    },
    [loadTodos],
  );

  const loadTodosByLabel = useCallback(async () =>
    // label: string
    {
      // TODO: Label filtering would need to be implemented in the API
      // For now, we'll load all todos and filter client-side
      await loadTodos();
    }, [loadTodos]);

  return {
    // Filtered data
    todos: allTodos,

    // Raw data from context
    allTodos,
    projects,
    labels,
    counts,

    // State
    loading,
    error,

    // Actions
    loadTodos,
    createTodo,
    updateTodo,
    deleteTodo,
    loadProjects,
    loadLabels,
    loadCounts,
    refreshAll,
    refresh,

    // Convenience methods
    loadTodayTodos,
    loadUpcomingTodos,
    loadCompletedTodos,
    loadTodosByPriority,
    loadTodosByProject,
    loadTodosByLabel,
  };
}
