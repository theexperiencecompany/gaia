"use client";

import { CheckmarkCircle02Icon } from "@icons";
import { m } from "motion/react";
import type { TodoResults } from "../../types/websocket";

type TodosRevealCardProps = TodoResults;

export function TodosRevealCard({ todos }: TodosRevealCardProps) {
  return (
    <m.div
      className="overflow-hidden rounded-xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        Created{" "}
        <span className="font-medium text-zinc-300">{todos.length}</span>{" "}
        {todos.length === 1 ? "todo" : "todos"}
      </p>
      {todos.length > 0 && (
        <div className="flex flex-col gap-2">
          {todos.map((todo) => (
            <div key={todo.id} className="flex items-center gap-2">
              <CheckmarkCircle02Icon className="size-3.5 shrink-0 text-zinc-500" />
              <span className="truncate text-sm text-zinc-300">
                {todo.title}
              </span>
            </div>
          ))}
        </div>
      )}
    </m.div>
  );
}
