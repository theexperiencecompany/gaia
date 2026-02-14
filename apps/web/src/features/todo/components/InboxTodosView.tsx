"use client";

import { CheckmarkCircle02Icon, Loading02Icon } from "@icons";
import { memo, useCallback, useMemo, useState } from "react";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import TodoItem from "@/features/todo/components/TodoItem";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import type { Todo, TodoUpdate } from "@/types/features/todoTypes";

interface InboxTodosViewProps {
  onRefresh?: () => void;
}

const InboxTodosView: React.FC<InboxTodosViewProps> = memo(({ onRefresh }) => {
  const [selectedTodo, setSelectedTodo] = useState<string | null>(null);

  // Stable filters object using useMemo
  const filters = useMemo(() => ({ completed: false }), []);

  // Fetch inbox todos (completed=false, no filters)
  const { todos, projects, loading, updateTodo, refresh } = useTodoData({
    filters,
    autoLoad: true,
  });

  // Memoize first 5 todos to prevent unnecessary re-renders
  const displayTodos = useMemo(() => todos.slice(0, 5), [todos]);

  const handleTodoUpdate = useCallback(
    async (todoId: string, updates: TodoUpdate) => {
      await updateTodo(todoId, updates);
    },
    [updateTodo],
  );

  const handleTodoClick = useCallback((todo: Todo) => {
    setSelectedTodo(todo.id);
  }, []);

  const handleRefresh = useCallback(() => {
    refresh();
    onRefresh?.();
  }, [refresh, onRefresh]);

  const isEmpty = !loading && todos.length === 0;

  return (
    <BaseCardView
      title="Inbox Todos"
      icon={<CheckmarkCircle02Icon className="h-6 w-6 text-zinc-500" />}
      isFetching={loading}
      isEmpty={isEmpty}
      emptyMessage="No todos in your inbox"
      errorMessage="Failed to load todos"
      path="/todos"
      onRefresh={handleRefresh}
    >
      {loading ? (
        <div className="flex h-full items-center justify-center">
          <Loading02Icon className="h-8 w-8 animate-spin text-zinc-500" />
        </div>
      ) : (
        <div className="space-y-0">
          {displayTodos.map((todo: Todo) => (
            <TodoItem
              key={todo.id}
              todo={todo}
              projects={projects}
              isSelected={selectedTodo === todo.id}
              onUpdate={handleTodoUpdate}
              onClick={handleTodoClick}
            />
          ))}
        </div>
      )}
    </BaseCardView>
  );
});

InboxTodosView.displayName = "InboxTodosView";

export default InboxTodosView;
