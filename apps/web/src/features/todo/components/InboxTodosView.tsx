"use client";

import {
  Alert01Icon,
  BubbleChatAddIcon,
  ChartLineData01Icon,
  CheckmarkCircle02Icon,
  FlashIcon,
  Flowchart01Icon,
  Loading02Icon,
  TaskDailyIcon,
} from "@icons";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import type { CardAction } from "@/features/chat/components/interface/BaseCardView";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import TodoItem from "@/features/todo/components/TodoItem";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useAppendToInput } from "@/stores/composerStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useTodoStore } from "@/stores/todoStore";
import type { Todo, TodoUpdate } from "@/types/features/todoTypes";

interface InboxTodosViewProps {
  onRefresh?: () => void;
}

const InboxTodosView: React.FC<InboxTodosViewProps> = memo(({ onRefresh }) => {
  const [selectedTodoId, setSelectedTodoId] = useState<string | null>(null);
  const appendToInput = useAppendToInput();

  const openWithContent = useRightSidebar((state) => state.openWithContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  // initialLoading is true only before the very first fetch completes.
  // After that it stays false even on background refetches — avoids skeleton flash on navigation.
  const initialLoading = useTodoStore((state) => state.initialLoading);

  const filters = useMemo(() => ({ completed: false }), []);

  const { todos, projects, loading, updateTodo, deleteTodo, refresh } =
    useTodoData({
      filters,
      autoLoad: true,
    });

  const displayTodos = useMemo(() => todos.slice(0, 5), [todos]);

  const updateTodoRef = useRef(updateTodo);
  const deleteTodoRef = useRef(deleteTodo);
  updateTodoRef.current = updateTodo;
  deleteTodoRef.current = deleteTodo;

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
        setSelectedTodoId(null);
        closeRightSidebar();
      } catch (error) {
        console.error("Failed to delete todo:", error);
      }
    },
    [closeRightSidebar],
  );

  const handleRefresh = useCallback(() => {
    refresh();
    onRefresh?.();
  }, [refresh, onRefresh]);

  const selectedTodo = useMemo(
    () =>
      selectedTodoId
        ? (todos.find((t) => t.id === selectedTodoId) ?? null)
        : null,
    [selectedTodoId, todos],
  );

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

  // Open sidebar when a todo is selected
  useEffect(() => {
    if (sidebarContent) {
      openWithContent(sidebarContent, "sheet");
    }
  }, [sidebarContent, openWithContent]);

  // Clear local selection when sidebar is closed externally (X button)
  useEffect(() => {
    return useRightSidebar.subscribe((state, prevState) => {
      if (prevState.isOpen && !state.isOpen && selectedTodoId) {
        setSelectedTodoId(null);
      }
    });
  }, [selectedTodoId]);

  const handleTodoClick = useCallback((todo: Todo) => {
    setSelectedTodoId(todo.id);
  }, []);

  // Only show empty state when not loading at all and there truly are no todos
  const isEmpty = !initialLoading && !loading && todos.length === 0;

  const actions: CardAction[] = useMemo(
    () => [
      {
        key: "plan-day",
        icon: <TaskDailyIcon className="size-4 text-zinc-400" />,
        label: "Plan my day",
        description:
          "Get a time-blocked schedule using todos, due dates, and calendar",
        onPress: () =>
          appendToInput(
            "Look at my inbox todos, their due dates, and today's calendar events. Give me a time-blocked plan for today — tell me what to work on, in what order, and when.",
          ),
      },
      {
        key: "top-three",
        icon: <FlashIcon className="size-4 text-zinc-400" />,
        label: "What are my top 3 today?",
        description: "Pick the three highest-impact tasks to finish before EOD",
        onPress: () =>
          appendToInput(
            "Based on my inbox todos, their priorities, and due dates, tell me the 3 most important things I should finish today and explain why each one matters.",
          ),
      },
      {
        key: "slipping",
        icon: <Alert01Icon className="size-4 text-zinc-400" />,
        label: "Find what's slipping",
        description:
          "Surface overdue or stale tasks and decide what to do with them",
        onPress: () =>
          appendToInput(
            "Look through my todos and identify everything that's overdue or hasn't been touched in over a week. For each one, suggest whether I should complete it, reschedule it, delegate it, or delete it.",
          ),
      },
      {
        key: "break-down",
        icon: <Flowchart01Icon className="size-4 text-zinc-400" />,
        label: "Break down big tasks",
        description: "Decompose complex todos into ordered subtasks",
        onPress: () =>
          appendToInput(
            "Look at my inbox todos and identify any that are too large or vague to action directly. For each one, break it down into clear, ordered subtasks I can actually complete.",
          ),
      },
      {
        key: "capture",
        icon: <BubbleChatAddIcon className="size-4 text-zinc-400" />,
        label: "Capture action items",
        description:
          "Scan recent emails and conversations for commitments I haven't captured",
        onPress: () =>
          appendToInput(
            "Scan my recent emails and GAIA conversations for any commitments, promises, or action items I've made that aren't already captured as todos. Create todos for anything you find.",
          ),
      },
      {
        key: "weekly-review",
        icon: <ChartLineData01Icon className="size-4 text-zinc-400" />,
        label: "Weekly review",
        description:
          "Summarise completions, slippage, and what to focus on next week",
        onPress: () =>
          appendToInput(
            "Run a weekly review for me. Summarise what todos I completed this week, what slipped, and recommend the top priorities I should focus on next week.",
          ),
      },
    ],
    [appendToInput],
  );

  return (
    <BaseCardView
      title="Inbox Todos"
      icon={<CheckmarkCircle02Icon className="h-6 w-6 text-zinc-500" />}
      isFetching={loading}
      isEmpty={isEmpty}
      emptyMessage="No todos in your inbox"
      errorMessage="Failed to load todos"
      onRefresh={handleRefresh}
      path="/todos"
      actions={actions}
    >
      {initialLoading ? (
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
              isSelected={selectedTodoId === todo.id}
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
