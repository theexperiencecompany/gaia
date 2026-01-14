"use client";

import { useMemo } from "react";

import type { Project, Todo, TodoUpdate } from "@/types/features/todoTypes";

import TodoItem from "./TodoItem";

interface TodoListProps {
  todos: Todo[];
  projects: Project[];
  onTodoUpdate: (todoId: string, updates: TodoUpdate) => void;
  // onTodoDelete: (todoId: string) => void;
  onTodoClick?: (todo: Todo) => void;
  // onTodoEdit?: (todo: Todo) => void;
  onRefresh?: () => void;
}

export default function TodoList({
  todos,
  projects,
  onTodoUpdate,
  // onTodoDelete,
  onTodoClick,
  // onTodoEdit,
}: TodoListProps) {
  const sortedTodos = useMemo(() => {
    return [...todos].sort((a, b) => Number(a.completed) - Number(b.completed));
  }, [todos]);

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
      <div className="w-full space-y-1 py-4 divide-y divide-surface-200">
        {sortedTodos.map((todo) => (
          <TodoItem
            key={todo.id}
            todo={todo}
            isSelected={false}
            projects={projects}
            onUpdate={onTodoUpdate}
            // onDelete={onTodoDelete}
            // onEdit={onTodoEdit}
            onClick={onTodoClick}
          />
        ))}
      </div>
    </div>
  );
}
