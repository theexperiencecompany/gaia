"use client";

import { ArrowRight01Icon, CheckmarkCircle02Icon, Mail01Icon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { useState } from "react";

interface OnboardingTodo {
  id: string;
  title: string;
  description?: string;
  source_email?: { sender: string; subject: string };
}

interface OnboardingTodoCardsProps {
  todos: OnboardingTodo[];
  onExecuteTodo: (todoId: string) => void;
  isExecuting: boolean;
  executingTodoId: string | null;
  completedTodoIds?: Set<string>;
}

const MAX_VISIBLE = 5;

function extractSenderName(sender: string): string {
  const match = sender.match(/^([^<]+)</);
  if (match) return match[1].trim();
  return sender.split("@")[0] ?? sender;
}

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
              className={`relative overflow-hidden rounded-2xl bg-zinc-800/60 ${
                active ? "border-l-2 border-l-violet-500" : ""
              }`}
              initial={{ opacity: 0, y: 12, scale: 0.97 }}
              animate={{ opacity: completed ? 0.6 : 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{
                delay: index * 0.06,
                type: "spring",
                stiffness: 300,
                damping: 24,
              }}
              onMouseEnter={() => setHoveredId(todo.id)}
              onMouseLeave={() => setHoveredId(null)}
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

              <div className="relative flex items-start gap-3 px-4 py-3 pr-28">
                <div className="mt-0.5 shrink-0">
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
                    <div className="size-5 rounded-full border-2 border-dashed border-zinc-600 mt-1" />
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
                  {todo.source_email && (
                    <div className="mt-1 flex items-center gap-1.5">
                      <Mail01Icon className="size-3 shrink-0 text-zinc-500" />
                      <span className="truncate text-xs text-zinc-500">
                        <span className="text-zinc-400">
                          {extractSenderName(todo.source_email.sender)}
                        </span>
                        {todo.source_email.subject && (
                          <>
                            <span className="mx-1 text-zinc-600">·</span>
                            {todo.source_email.subject}
                          </>
                        )}
                      </span>
                    </div>
                  )}
                  {!todo.source_email && todo.description && (
                    <p className="mt-0.5 truncate text-xs text-zinc-400">
                      {todo.description}
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  aria-hidden={!hovered || isExecuting}
                  className={`absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5 rounded-lg bg-zinc-700/60 px-2.5 py-1 text-xs font-medium text-zinc-200 transition-opacity duration-150 hover:bg-zinc-600/60 ${
                    hovered && !isExecuting
                      ? "opacity-100"
                      : "pointer-events-none opacity-0"
                  }`}
                  onClick={() => handleExecute(todo.id)}
                >
                  Run now
                  <ArrowRight01Icon className="size-3" />
                </button>
              </div>
            </m.div>
          );
        })}
      </AnimatePresence>
    </m.div>
  );
}
