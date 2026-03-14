"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import Spinner from "@/components/ui/spinner";
import TodoList from "@/features/todo/components/TodoList";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useUrlTodoSelection } from "@/features/todo/hooks/useUrlTodoSelection";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useTodoStore } from "@/stores/todoStore";
import type { Todo, TodoFilters, TodoUpdate } from "@/types/features/todoTypes";

interface TodoListPageProps {
  filters?: TodoFilters;
  filterTodos?: (todos: Todo[]) => Todo[];
}

export default function TodoListPage({
  filters,
  filterTodos,
}: TodoListPageProps) {
  const { selectedTodoId, selectTodo, clearSelection } = useUrlTodoSelection();
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Get right sidebar actions - these are stable from Zustand
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  // Individual selectors to avoid re-renders from unrelated store changes
  const storeTodos = useTodoStore((state) => state.todos);
  const storeProjects = useTodoStore((state) => state.projects);

  // Use useTodoData for initial load and actions
  const {
    todos: dataTodos,
    projects: dataProjects,
    loading,
    updateTodo,
    deleteTodo,
    refresh,
  } = useTodoData({ filters, autoLoad: true });

  // Merge todos: prefer store (for real-time updates) but fallback to data
  const todos = useMemo(() => {
    const baseTodos = storeTodos.length > 0 ? storeTodos : dataTodos;
    if (filterTodos) return filterTodos(baseTodos);
    return baseTodos;
  }, [storeTodos, dataTodos, filterTodos]);

  // Merge projects similarly
  const projects = useMemo(() => {
    return storeProjects.length > 0 ? storeProjects : dataProjects;
  }, [storeProjects, dataProjects]);

  // Use refs to store latest callback versions to avoid stale closures
  const updateTodoRef = useRef(updateTodo);
  const deleteTodoRef = useRef(deleteTodo);
  updateTodoRef.current = updateTodo;
  deleteTodoRef.current = deleteTodo;

  // Stable callbacks that don't change reference
  const handleTodoUpdate = useCallback(
    async (todoId: string, updates: TodoUpdate) => {
      try {
        await updateTodoRef.current(todoId, updates);
      } catch (error) {
        console.error("Failed to update todo:", error);
      }
    },
    [],
  );

  const handleTodoDelete = useCallback(async (todoId: string) => {
    try {
      await deleteTodoRef.current(todoId);
    } catch (error) {
      console.error("Failed to delete todo:", error);
    }
  }, []);

  // Stable click handler
  const handleTodoClick = useCallback(
    (todo: Todo) => {
      selectTodo(todo.id);
    },
    [selectTodo],
  );

  const handlePrefetchWorkflow = useCallback((todoId: string) => {
    useTodoStore.getState().prefetchWorkflowStatus(todoId);
  }, []);

  // Find the selected todo from the merged list
  const selectedTodo = useMemo(() => {
    if (!selectedTodoId) return null;
    return todos.find((t) => t.id === selectedTodoId) || null;
  }, [selectedTodoId, todos]);

  // Memoize sidebar content so setRightSidebarContent only gets a new element
  // when the selected todo or its data actually changes — not on every store update.
  const sidebarContent = useMemo(() => {
    if (!selectedTodo) return null;
    return (
      <TodoSidebar
        todo={selectedTodo}
        onUpdate={handleTodoUpdate}
        onDelete={handleTodoDelete}
        projects={projects}
      />
    );
  }, [selectedTodo, handleTodoUpdate, handleTodoDelete, projects]);

  // Effect: Sync selected todo with right sidebar
  useEffect(() => {
    if (sidebarContent && selectedTodo) {
      setRightSidebarContent(sidebarContent);
      openRightSidebar("sheet");
    } else if (selectedTodoId && todos.length > 0) {
      // selectedTodoId exists but todo not found - clear selection
      clearSelection();
      closeRightSidebar();
    } else if (!selectedTodoId) {
      // No selection - ensure sidebar is closed
      setRightSidebarContent(null);
      closeRightSidebar();
    }
  }, [
    sidebarContent,
    selectedTodo,
    selectedTodoId,
    todos.length,
    setRightSidebarContent,
    openRightSidebar,
    closeRightSidebar,
    clearSelection,
  ]);

  // Effect: Handle sidebar close from external trigger (e.g., X button)
  useEffect(() => {
    const unsubscribe = useRightSidebar.subscribe((state, prevState) => {
      if (prevState.isOpen && !state.isOpen && selectedTodoId) {
        clearSelection();
      }
    });

    return unsubscribe;
  }, [selectedTodoId, clearSelection]);

  // Effect: Handle todo deletion while selected
  useEffect(() => {
    if (selectedTodoId && todos.length > 0) {
      const todoExists = todos.some((t) => t.id === selectedTodoId);
      if (!todoExists) {
        clearSelection();
        closeRightSidebar();
      }
    }
  }, [selectedTodoId, todos, clearSelection, closeRightSidebar]);

  // Effect: Cleanup on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  // Loading state
  if (loading && todos.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col">
      <div ref={scrollContainerRef} className="w-full flex-1 overflow-y-auto px-4">
        <TodoList
          todos={todos}
          onTodoUpdate={handleTodoUpdate}
          projects={projects}
          selectedTodoId={selectedTodoId ?? undefined}
          onTodoClick={handleTodoClick}
          onRefresh={refresh}
          onPrefetchWorkflow={handlePrefetchWorkflow}
          scrollContainerRef={scrollContainerRef}
        />
      </div>
    </div>
  );
}
