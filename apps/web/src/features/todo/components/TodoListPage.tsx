"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { todoApi } from "@/features/todo/api/todoApi";
import TodoList from "@/features/todo/components/TodoList";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useUrlTodoSelection } from "@/features/todo/hooks/useUrlTodoSelection";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useTodoStore } from "@/stores/todoStore";
import type { Todo, TodoFilters, TodoUpdate } from "@/types/features/todoTypes";

function TodoItemSkeleton() {
  return (
    <div className="w-full p-2 pl-3 pt-6">
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <Skeleton className="mt-1 h-5 w-5 rounded-full bg-zinc-700" />
        {/* Content */}
        <div className="min-w-0 flex-1">
          <Skeleton className="h-5 w-3/5 bg-zinc-700" />
          <Skeleton className="mt-2 h-3 w-2/5 bg-zinc-700" />
          <div className="mt-3 flex flex-wrap items-center gap-1">
            <Skeleton className="h-6 w-24 rounded-lg bg-zinc-700" />
            <Skeleton className="h-6 w-20 rounded-lg bg-zinc-700" />
            <Skeleton className="h-6 w-16 rounded-lg bg-zinc-700" />
            <Skeleton className="h-6 w-28 rounded-lg bg-zinc-700" />
            <Skeleton className="h-6 w-14 rounded-lg bg-zinc-700" />
          </div>
        </div>
        {/* Workflow category icons — matches real 22x22 in min-w-7 containers */}
        <div className="flex min-h-8 items-center -space-x-1.5 self-center">
          <div
            className="relative flex min-w-7 items-center justify-center"
            style={{ rotate: "8deg" }}
          >
            <Skeleton className="h-[22px] w-[22px] rounded-md bg-zinc-700" />
          </div>
          <div
            className="relative flex min-w-7 items-center justify-center"
            style={{ rotate: "-8deg" }}
          >
            <Skeleton className="h-[22px] w-[22px] rounded-md bg-zinc-700" />
          </div>
          <div
            className="relative flex min-w-7 items-center justify-center"
            style={{ rotate: "8deg" }}
          >
            <Skeleton className="h-[22px] w-[22px] rounded-md bg-zinc-700" />
          </div>
        </div>
      </div>
    </div>
  );
}

const SKELETON_KEYS = ["sk-1", "sk-2", "sk-3", "sk-4", "sk-5", "sk-6"];

function TodoListSkeleton() {
  return (
    <div className="flex w-full justify-center">
      <div className="w-full">
        {SKELETON_KEYS.map((key) => (
          <TodoItemSkeleton key={key} />
        ))}
      </div>
    </div>
  );
}

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

  // Deep-link fallback: a todo opened via ?todoId= may not be in the loaded
  // (filtered/paginated) list — e.g. a dormant todo linked from a notification.
  // In that case we fetch it by id so the sidebar still opens. `notFoundId`
  // records an id confirmed missing (404) so we clear instead of refetching.
  const [fetchedTodo, setFetchedTodo] = useState<Todo | null>(null);
  const [notFoundId, setNotFoundId] = useState<string | null>(null);

  // Get right sidebar actions - these are stable from Zustand
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const openWithContent = useRightSidebar((state) => state.openWithContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  // Individual selectors to avoid re-renders from unrelated store changes
  const storeTodos = useTodoStore((state) => state.todos);
  const storeProjects = useTodoStore((state) => state.projects);
  const initialLoading = useTodoStore((state) => state.initialLoading);

  // Use useTodoData for initial load and actions
  const {
    todos: dataTodos,
    projects: dataProjects,
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
  const clearSelectionRef = useRef(clearSelection);
  updateTodoRef.current = updateTodo;
  deleteTodoRef.current = deleteTodo;
  clearSelectionRef.current = clearSelection;

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

  const handleTodoDelete = useCallback(
    async (todoId: string) => {
      try {
        await deleteTodoRef.current(todoId);
      } catch (error) {
        console.error("Failed to delete todo:", error);
      }
      // Always close sidebar after deletion — effects alone miss the case
      // where the deleted todo was the last one in the current filtered view
      clearSelectionRef.current();
      closeRightSidebar();
    },
    [closeRightSidebar],
  );

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

  // Find the selected todo: prefer the loaded list, fall back to the todo
  // fetched by id for deep links that point outside the current view.
  const selectedTodo = useMemo(() => {
    if (!selectedTodoId) return null;
    const inList = todos.find((t) => t.id === selectedTodoId);
    if (inList) return inList;
    return fetchedTodo?.id === selectedTodoId ? fetchedTodo : null;
  }, [selectedTodoId, todos, fetchedTodo]);

  // Fetch a deep-linked todo by id when it isn't in the loaded list.
  useEffect(() => {
    if (!selectedTodoId) return;
    if (todos.some((t) => t.id === selectedTodoId)) return; // already visible
    if (fetchedTodo?.id === selectedTodoId) return; // already fetched
    if (notFoundId === selectedTodoId) return; // already confirmed missing

    let cancelled = false;
    todoApi
      .getTodo(selectedTodoId)
      .then((todo) => {
        if (!cancelled) setFetchedTodo(todo);
      })
      .catch(() => {
        if (!cancelled) setNotFoundId(selectedTodoId);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTodoId, todos, fetchedTodo, notFoundId]);

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
      openWithContent(sidebarContent, "sheet");
    } else if (selectedTodoId && notFoundId === selectedTodoId) {
      // Confirmed missing (deleted/stale, fetch returned 404) - clear selection.
      // While a deep-linked todo is still being fetched we leave the selection
      // intact so the sidebar opens once it resolves.
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
    notFoundId,
    todos.length,
    setRightSidebarContent,
    openWithContent,
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

  // Effect: Cleanup on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  // Show skeleton on initial load only — subsequent filter changes keep stale todos visible
  if (initialLoading) {
    return (
      <div className="flex h-full w-full flex-col">
        <div className="w-full flex-1 overflow-y-auto px-4">
          <TodoListSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col">
      <div
        ref={scrollContainerRef}
        className="w-full flex-1 overflow-y-auto px-4"
      >
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
