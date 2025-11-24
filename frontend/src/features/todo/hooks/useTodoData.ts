"use client";

import { useCallback, useEffect } from "react";

import { useTodoStore } from "@/stores/todoStore";
import type { Priority, TodoFilters } from "@/types/features/todoTypes";

interface UseTodoDataOptions {
  filters?: TodoFilters;
  autoLoad?: boolean;
}

export function useTodoData(options: UseTodoDataOptions = {}) {
  const { filters, autoLoad = true } = options;
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

  // API handles filtering, so just return allTodos directly
  const todos = allTodos;

  // Load data on mount if autoLoad is enabled
  useEffect(() => {
    if (autoLoad) {
      loadTodos(filters);
    }
  }, [autoLoad, filters, loadTodos]);

  // Refresh function that reloads current filter
  const refresh = useCallback(() => {
    return loadTodos(filters);
  }, [loadTodos, filters]);

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
    todos,

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
