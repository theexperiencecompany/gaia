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

  // Track last loaded filters to avoid redundant fetches while still reloading on filter changes
  const prevFiltersRef = useRef<string | null>(null);

  // Load data on mount and whenever filters change — fire all three in parallel
  useEffect(() => {
    if (autoLoad && prevFiltersRef.current !== filtersString) {
      prevFiltersRef.current = filtersString;
      const parsedFilters = JSON.parse(filtersString) as TodoFilters;
      const todosPromise = loadTodos(parsedFilters);
      const projectsPromise = loadProjects();
      const countsPromise = loadCounts();
      Promise.all([todosPromise, projectsPromise, countsPromise]).catch(
        console.error,
      );
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
