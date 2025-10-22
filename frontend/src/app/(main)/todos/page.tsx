"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import TodoList from "@/features/todo/components/TodoList";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useUrlTodoSelection } from "@/features/todo/hooks/useUrlTodoSelection";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import {
  Priority,
  Todo,
  TodoFilters,
  TodoUpdate,
} from "@/types/features/todoTypes";

export default function TodosPage() {
  const searchParams = useSearchParams();
  const { selectedTodoId, selectTodo, clearSelection } = useUrlTodoSelection();
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  // Get filter from URL params
  const projectId = searchParams.get("project");
  const priority = searchParams.get("priority");
  const completedParam = searchParams.get("completed");
  const completed = completedParam === "true";

  // Helper function to validate priority value
  const getPriorityFilter = (
    priorityString: string | null,
  ): Priority | undefined => {
    if (!priorityString) return undefined;
    return Object.values(Priority).includes(priorityString as Priority)
      ? (priorityString as Priority)
      : undefined;
  };

  // Build filters from URL params
  const filters = useMemo((): TodoFilters => {
    const urlFilters: TodoFilters = {};

    // Only add filters if they are explicitly specified in URL
    if (projectId) {
      urlFilters.project_id = projectId;
    }

    if (priority) {
      const priorityValue = getPriorityFilter(priority);
      if (priorityValue) {
        urlFilters.priority = priorityValue;
      }
    }

    // Handle completed filter - always default to false for inbox
    urlFilters.completed = completedParam === "true" ? true : false;

    return urlFilters;
  }, [projectId, priority, completedParam]);

  const { todos, projects, loading, updateTodo, deleteTodo, refresh } =
    useTodoData({ filters, autoLoad: true });

  const handleTodoUpdate = async (todoId: string, updates: TodoUpdate) => {
    await updateTodo(todoId, updates);
  };

  const handleTodoDelete = async (todoId: string) => {
    await deleteTodo(todoId);
    // If the deleted todo was selected (shown in URL), close the detail sheet
    if (selectedTodoId === todoId) {
      clearSelection();
      closeRightSidebar();
    }
  };

  const handleTodoEdit = (todo: Todo) => {
    selectTodo(todo.id);
  };

  // Memoize the close handler
  const handleClose = useCallback(() => {
    clearSelection();
    closeRightSidebar();
  }, [clearSelection, closeRightSidebar]);

  // Sync todo sidebar with right sidebar
  useEffect(() => {
    const selectedTodo = selectedTodoId
      ? todos.find((t: Todo) => t.id === selectedTodoId) || null
      : null;

    if (selectedTodo) {
      setRightSidebarContent(
        <TodoSidebar
          todo={selectedTodo}
          onUpdate={handleTodoUpdate}
          onDelete={handleTodoDelete}
          projects={projects}
        />,
      );
    } else {
      setRightSidebarContent(null);
    }
  }, [
    selectedTodoId,
    todos,
    projects,
    handleClose,
    setRightSidebarContent,
    handleTodoUpdate,
    handleTodoDelete,
  ]);

  // Cleanup right sidebar on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  if (loading && todos.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <div className="flex h-full w-full flex-col">
      <div className="w-full flex-1 overflow-y-auto px-4">
        <TodoList
          todos={todos}
          onTodoUpdate={handleTodoUpdate}
          onTodoDelete={handleTodoDelete}
          onTodoEdit={handleTodoEdit}
          onTodoClick={(todo) => selectTodo(todo.id)}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}
