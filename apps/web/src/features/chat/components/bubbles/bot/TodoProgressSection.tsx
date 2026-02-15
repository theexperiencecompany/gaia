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

function SourceCard({
  source,
  todos,
}: {
  source: string;
  todos: TodoProgressItem[];
}) {
  const completedCount = todos.filter((t) => t.status === "completed").length;

  return (
    <div className="min-w-[280px] max-w-[420px] flex-1 rounded-xl bg-zinc-800/60 px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-400">{source}</span>
        <span className="text-xs text-zinc-500">
          {completedCount}/{todos.length}
        </span>
      </div>
      <div className="space-y-1">
        {todos.map((todo) => (
          <div key={todo.id} className="flex items-start gap-2">
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
    </div>
  );
}

export default function TodoProgressSection({
  todo_progress,
}: TodoProgressSectionProps) {
  const sources = Object.keys(todo_progress);
  if (sources.length === 0) return null;

  // Filter out sources with no todos
  const activeSources = sources.filter(
    (s) => todo_progress[s]?.todos && todo_progress[s].todos.length > 0,
  );
  if (activeSources.length === 0) return null;

  // Single source: render a compact card (backward compatible)
  if (activeSources.length === 1) {
    const source = activeSources[0];
    return (
      <div className="mt-2 mb-2">
        <SourceCard source={source} todos={todo_progress[source].todos} />
      </div>
    );
  }

  // Multiple sources: render separate cards side by side
  return (
    <div className="mt-2 mb-2 flex flex-wrap gap-2">
      {activeSources.map((source) => (
        <SourceCard
          key={source}
          source={source}
          todos={todo_progress[source].todos}
        />
      ))}
    </div>
  );
}
