"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo } from "react";

import type { Project, Todo, TodoUpdate } from "@/types/features/todoTypes";

import TodoItem from "./TodoItem";

interface TodoListProps {
  todos: Todo[];
  projects: Project[];
  selectedTodoId?: string;
  onTodoUpdate: (todoId: string, updates: TodoUpdate) => void;
  onTodoClick?: (todo: Todo) => void;
  onRefresh?: () => void;
  onPrefetchWorkflow?: (todoId: string) => void;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
}

export default function TodoList({
  todos,
  projects,
  selectedTodoId,
  onTodoUpdate,
  onTodoClick,
  onPrefetchWorkflow,
  scrollContainerRef,
}: TodoListProps) {
  const sortedTodos = useMemo(() => {
    return [...todos].sort((a, b) => Number(a.completed) - Number(b.completed));
  }, [todos]);

  const virtualizer = useVirtualizer({
    count: sortedTodos.length,
    getScrollElement: () => scrollContainerRef?.current ?? null,
    estimateSize: () => 72,
    overscan: 5,
    paddingStart: 16,
    paddingEnd: 16,
  });

  if (sortedTodos.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-foreground-500 sm:min-w-5xl">
        <p className="mb-2 text-lg">No tasks found</p>
        <p className="text-sm">Create a new task to get started</p>
      </div>
    );
  }

  return (
    <div className="flex w-full justify-center">
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => {
          const todo = sortedTodos[virtualItem.index];
          return (
            <div
              key={virtualItem.key}
              data-index={virtualItem.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualItem.start}px)`,
              }}
              // className="border-b border-zinc-800"
            >
              <TodoItem
                todo={todo}
                isSelected={todo.id === selectedTodoId}
                projects={projects}
                onUpdate={onTodoUpdate}
                onClick={onTodoClick}
                onPrefetchWorkflow={onPrefetchWorkflow}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
