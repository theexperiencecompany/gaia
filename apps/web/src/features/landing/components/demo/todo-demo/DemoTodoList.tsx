"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import { CalendarCheckOut01Icon, Flag02Icon, Tag01Icon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { ChevronRight } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  DEMO_TODOS,
  PRIORITY_CHIP,
  PRIORITY_RING,
  TARGET_TODO,
  type TodoDemoPhase,
  tdEase,
} from "./todoDemoConstants";

interface DemoTodoListProps {
  phase: TodoDemoPhase;
}

export default function DemoTodoList({ phase }: DemoTodoListProps) {
  const isHighlighting = phase === "todo_highlighted";

  return (
    <m.div
      key="todo-list"
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease: tdEase }}
      className="mx-auto w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl"
    >
      {/* Header */}
      <div className="border-b border-zinc-800 px-5 py-3.5">
        <span className="text-sm font-medium text-zinc-300">Inbox</span>
        <span className="ml-2 rounded-full bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500">
          {DEMO_TODOS.length}
        </span>
      </div>

      {/* Todo rows */}
      <div className="divide-y divide-zinc-800/60">
        <AnimatePresence>
          {DEMO_TODOS.map((todo, index) => {
            const isTarget = todo.id === TARGET_TODO.id;
            const highlight = isHighlighting && isTarget;
            const dimmed = isHighlighting && !isTarget;

            return (
              <m.div
                key={todo.id}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  duration: 0.5,
                  ease: tdEase,
                  delay: index * 0.12,
                }}
              >
                {/* Inner div handles highlight bg/ring and instant dimming */}
                <div
                  className={`relative flex items-start gap-3 p-4 pl-5 ${
                    highlight
                      ? "bg-primary/8 ring-1 ring-inset ring-primary/40"
                      : "hover:bg-zinc-800/40"
                  }`}
                  style={{ opacity: dimmed ? 0.4 : 1 }}
                >
                  {/* Checkbox */}
                  <Checkbox
                    isSelected={false}
                    color={
                      todo.priority === "high"
                        ? "danger"
                        : todo.priority === "medium"
                          ? "warning"
                          : "primary"
                    }
                    radius="full"
                    classNames={{
                      wrapper: `mt-1 shrink-0 ${PRIORITY_RING[todo.priority]} border-dashed border-1 before:border-0 bg-zinc-900`,
                    }}
                  />

                  {/* Content */}
                  <div className="min-w-0 flex-1">
                    <p className="text-base font-medium text-zinc-100">
                      {todo.title}
                    </p>

                    {todo.description && (
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {todo.description}
                      </p>
                    )}

                    {/* Chips row */}
                    <div className="mt-2 flex flex-wrap items-center gap-1">
                      <Chip
                        size="sm"
                        variant="flat"
                        radius="sm"
                        className="px-1 text-zinc-400"
                        startContent={
                          <CalendarCheckOut01Icon
                            width={16}
                            height={16}
                            className="mx-1"
                          />
                        }
                      >
                        {todo.dueDate}
                      </Chip>

                      {todo.labels.map((label) => (
                        <Chip
                          key={label}
                          size="sm"
                          variant="flat"
                          radius="sm"
                          className="px-1 text-zinc-400"
                          startContent={
                            <Tag01Icon
                              width={17}
                              height={17}
                              className="mx-1"
                            />
                          }
                        >
                          {label.charAt(0).toUpperCase() + label.slice(1)}
                        </Chip>
                      ))}

                      <Chip
                        size="sm"
                        variant="flat"
                        radius="sm"
                        className={`px-1 ${PRIORITY_CHIP[todo.priority]}`}
                        startContent={
                          <Flag02Icon width={15} height={15} className="mx-1" />
                        }
                      >
                        {todo.priority.charAt(0).toUpperCase() +
                          todo.priority.slice(1)}
                      </Chip>
                    </div>
                  </div>

                  {/* Workflow Category Icons */}
                  {todo.workflowCategories.length > 0 && (
                    <div className="flex min-h-8 items-center -space-x-1.5 self-center">
                      {todo.workflowCategories
                        .slice(0, 3)
                        .map((category, i) => {
                          const IconComponent = getToolCategoryIcon(category, {
                            width: 22,
                            height: 22,
                          });
                          return IconComponent ? (
                            <div
                              key={category}
                              className="relative flex min-w-7 items-center justify-center"
                              style={{
                                rotate:
                                  todo.workflowCategories.length > 1
                                    ? i % 2 === 0
                                      ? "8deg"
                                      : "-8deg"
                                    : "0deg",
                                zIndex: i,
                              }}
                            >
                              {IconComponent}
                            </div>
                          ) : null;
                        })}
                      {todo.workflowCategories.length > 3 && (
                        <div className="z-0 flex size-[28px] min-h-[28px] min-w-[28px] items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500">
                          +{todo.workflowCategories.length - 3}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Chevron */}
                  <div className="flex h-full items-center self-center">
                    <ChevronRight
                      width={20}
                      height={20}
                      className="text-zinc-400"
                    />
                  </div>

                  {/* Highlight pulse ring */}
                  {highlight && (
                    <m.div
                      className="pointer-events-none absolute inset-0 rounded-none ring-1 ring-primary/50"
                      animate={{ opacity: [0.6, 1, 0.6] }}
                      transition={{ duration: 1.4, repeat: Infinity }}
                    />
                  )}
                </div>
              </m.div>
            );
          })}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
