"use client";

import { ArrowRight01Icon, CheckmarkCircle02Icon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { useState } from "react";

interface OnboardingTodoCardsProps {
  todos: Array<{ id: string; title: string; description?: string }>;
  onExecuteTodo: (todoId: string) => void;
  isExecuting: boolean;
  executingTodoId: string | null;
  completedTodoIds?: Set<string>;
}

const MAX_VISIBLE = 5;

export function OnboardingTodoCards({
  todos,
  onExecuteTodo,
  isExecuting,
  executingTodoId,
  completedTodoIds,
}: OnboardingTodoCardsProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const visibleTodos = todos.slice(0, MAX_VISIBLE);

  const handleExecute = (todoId: string) => {
    if (isExecuting) return;
    onExecuteTodo(todoId);
  };

  const isCompleted = (todoId: string) =>
    completedTodoIds?.has(todoId) ?? false;
  const isActive = (todoId: string) =>
    executingTodoId === todoId && isExecuting;

  return (
    <m.div
      className="flex flex-col gap-2"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <AnimatePresence mode="popLayout">
        {visibleTodos.map((todo, index) => {
          const completed = isCompleted(todo.id);
          const active = isActive(todo.id);
          const hovered = hoveredId === todo.id && !active && !completed;

          return (
            <m.div
              key={todo.id}
              layout
              className={`relative overflow-hidden rounded-2xl border bg-zinc-800/60 shadow-sm transition-colors ${
                active
                  ? "border-l-2 border-l-violet-500 border-t-zinc-700/50 border-r-zinc-700/50 border-b-zinc-700/50"
                  : completed
                    ? "border-zinc-700/30"
                    : "border-zinc-700/50"
              }`}
              initial={{ opacity: 0, y: 12, scale: 0.97 }}
              animate={{
                opacity: completed ? 0.6 : 1,
                y: 0,
                scale: 1,
              }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{
                delay: index * 0.06,
                type: "spring",
                stiffness: 300,
                damping: 24,
              }}
              onMouseEnter={() => setHoveredId(todo.id)}
              onMouseLeave={() => setHoveredId(null)}
              whileHover={
                !active && !completed ? { y: -2, scale: 1.01 } : undefined
              }
            >
              {active && (
                <m.div
                  className="absolute inset-0 rounded-2xl bg-violet-500/5"
                  animate={{ opacity: [0.3, 0.6, 0.3] }}
                  transition={{
                    duration: 1.8,
                    repeat: Number.POSITIVE_INFINITY,
                    ease: "easeInOut",
                  }}
                />
              )}

              <div className="relative flex items-center gap-3 px-4 py-3">
                <div className="shrink-0">
                  {completed ? (
                    <m.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{
                        type: "spring",
                        stiffness: 400,
                        damping: 15,
                      }}
                    >
                      <CheckmarkCircle02Icon className="size-4 text-emerald-400" />
                    </m.div>
                  ) : active ? (
                    <m.div
                      className="size-4 rounded-full border-2 border-violet-400 border-t-transparent"
                      animate={{ rotate: 360 }}
                      transition={{
                        duration: 0.8,
                        repeat: Number.POSITIVE_INFINITY,
                        ease: "linear",
                      }}
                    />
                  ) : (
                    <div className="size-4 rounded-full border border-zinc-600" />
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <p
                    className={`text-sm font-medium ${
                      completed ? "text-zinc-500 line-through" : "text-zinc-200"
                    }`}
                  >
                    {todo.title}
                  </p>
                  {todo.description && (
                    <p className="mt-0.5 truncate text-xs text-zinc-400">
                      {todo.description}
                    </p>
                  )}
                </div>

                <AnimatePresence>
                  {hovered && !isExecuting && (
                    <m.button
                      type="button"
                      className="flex shrink-0 items-center gap-1.5 rounded-lg bg-zinc-700/60 px-2.5 py-1 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-600/60"
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 8 }}
                      transition={{ duration: 0.15 }}
                      onClick={() => handleExecute(todo.id)}
                    >
                      Run now
                      <ArrowRight01Icon className="size-3" />
                    </m.button>
                  )}
                </AnimatePresence>
              </div>
            </m.div>
          );
        })}
      </AnimatePresence>
    </m.div>
  );
}
