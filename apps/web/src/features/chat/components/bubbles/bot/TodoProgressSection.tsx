"use client";

import React from "react";

import type {
  TodoProgressData,
  TodoProgressItem,
} from "@/types/features/todoProgressTypes";

interface TodoProgressSectionProps {
  todo_progress: TodoProgressData;
}

const STATUS_ICON: Record<TodoProgressItem["status"], string> = {
  completed: "\u2713",
  in_progress: "\u2192",
  cancelled: "\u2717",
  pending: "\u25CB",
};

const STATUS_COLOR: Record<TodoProgressItem["status"], string> = {
  completed: "text-green-400",
  in_progress: "text-blue-400",
  cancelled: "text-zinc-500 line-through",
  pending: "text-zinc-400",
};

export default function TodoProgressSection({
  todo_progress,
}: TodoProgressSectionProps) {
  // Flatten all sources into one ordered list (executor first, then others)
  const sources = Object.keys(todo_progress);
  if (sources.length === 0) return null;

  const allTodos: (TodoProgressItem & { source: string })[] = [];
  for (const source of sources) {
    const snapshot = todo_progress[source];
    if (snapshot?.todos) {
      for (const todo of snapshot.todos) {
        allTodos.push({ ...todo, source });
      }
    }
  }

  if (allTodos.length === 0) return null;

  const completedCount = allTodos.filter(
    (t) => t.status === "completed",
  ).length;
  const totalCount = allTodos.length;

  return (
    <div className="mt-2 mb-2 w-fit min-w-[320px] max-w-[480px] rounded-xl bg-zinc-800/60 px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-400">Task Progress</span>
        <span className="text-xs text-zinc-500">
          {completedCount}/{totalCount}
        </span>
      </div>
      <div className="space-y-1">
        {allTodos.map((todo) => (
          <div
            key={`${todo.source}-${todo.id}`}
            className="flex items-start gap-2"
          >
            <span
              className={`mt-px flex h-4 w-4 shrink-0 items-center justify-center text-xs font-medium ${STATUS_COLOR[todo.status]}`}
            >
              {STATUS_ICON[todo.status]}
            </span>
            <span
              className={`text-xs leading-relaxed ${STATUS_COLOR[todo.status]}`}
            >
              {todo.content}
            </span>
          </div>
        ))}
      </div>
      {sources.length > 1 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {sources.map((source) => (
            <span
              key={source}
              className="rounded-full bg-zinc-700/50 px-1.5 py-0.5 text-[10px] text-zinc-500"
            >
              {source}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
