"use client";

import { useCallback, useEffect, useMemo } from "react";

import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import Spinner from "@/components/ui/shadcn/spinner";
import TodoList from "@/features/todo/components/TodoList";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useUrlTodoSelection } from "@/features/todo/hooks/useUrlTodoSelection";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { Todo, TodoFilters, TodoUpdate } from "@/types/features/todoTypes";

interface TodoListPageProps {
  filters?: TodoFilters;
  filterTodos?: (todos: Todo[]) => Todo[];
}

export default function TodoListPage({
  filters,
  filterTodos,
}: TodoListPageProps) {
  const { selectedTodoId, selectTodo, clearSelection } = useUrlTodoSelection();
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  const {
    todos: allTodos,
    projects,
    loading,
    updateTodo,
    deleteTodo,
    refresh,
  } = useTodoData({ filters, autoLoad: true });

  // Apply additional client-side filtering if provided
  const todos = useMemo(() => {
    // Apply custom filter function if provided (for date range filtering that API doesn't support well)
    if (filterTodos) return filterTodos(allTodos);

    return allTodos;
  }, [allTodos, filterTodos]);

  const handleTodoUpdate = async (todoId: string, updates: TodoUpdate) => {
    try {
      await updateTodo(todoId, updates);
    } catch (error) {
      console.error("Failed to update todo:", error);
    }
  };

  const handleTodoDelete = async (todoId: string) => {
    try {
      await deleteTodo(todoId);
      // If the deleted todo was selected, close the detail sheet
      if (selectedTodoId === todoId) {
        clearSelection();
        closeRightSidebar();
      }
    } catch (error) {
      console.error("Failed to delete todo:", error);
    }
  };

  const handleTodoEdit = (todo: Todo) => {
    selectTodo(todo.id);
  };

  const handleTodoClick = (todo: Todo) => {
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
      ? allTodos.find((t: Todo) => t.id === selectedTodoId) || null
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
  }, [selectedTodoId, allTodos, projects, handleClose, setRightSidebarContent]);

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
          onTodoClick={handleTodoClick}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}
