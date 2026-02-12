"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import { motion } from "framer-motion";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  CalendarCheckOut01Icon,
  CheckmarkCircle02Icon,
  ChevronRight,
  Flag02Icon,
  Tag01Icon,
} from "@/icons";
import {
  DEMO_TODOS,
  PRIORITY_CHIP,
  PRIORITY_RING,
  TARGET_TODO,
  type TodoDemoPhase,
} from "./todoDemoConstants";

interface DemoTodoCompleteProps {
  phase: TodoDemoPhase;
}

export default function DemoTodoComplete({
  phase: _phase,
}: DemoTodoCompleteProps) {
  return (
    <motion.div
      key="todo-complete"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ type: "spring", stiffness: 340, damping: 28 }}
      className="mx-auto w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl"
    >
      {/* Header */}
      <div className="border-b border-zinc-800 px-5 py-3.5">
        <span className="text-sm font-medium text-zinc-300">Inbox</span>
      </div>

      {/* Todo rows */}
      <div className="divide-y divide-zinc-800/60">
        {DEMO_TODOS.map((todo, index) => {
          const isTarget = todo.id === TARGET_TODO.id;

          return (
            <motion.div
              key={todo.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: isTarget ? 1 : 0.45 }}
              transition={{ delay: index * 0.06, duration: 0.3 }}
              className={`relative flex items-start gap-3 p-4 pl-5 transition-all duration-300 ${
                isTarget ? "bg-success/5" : ""
              }`}
            >
              {/* Checkbox — completed for target */}
              {isTarget ? (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{
                    type: "spring",
                    stiffness: 500,
                    damping: 20,
                    delay: 0.2,
                  }}
                  className="mt-1 shrink-0"
                >
                  <CheckmarkCircle02Icon
                    width={18}
                    height={18}
                    className="text-success"
                  />
                </motion.div>
              ) : (
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
              )}

              {/* Content */}
              <div className="min-w-0 flex-1">
                <motion.p
                  animate={isTarget ? { opacity: 0.4 } : { opacity: 1 }}
                  transition={{ delay: 0.3, duration: 0.4 }}
                  className={`text-base font-medium ${
                    isTarget ? "text-zinc-400 line-through" : "text-zinc-100"
                  }`}
                >
                  {todo.title}
                </motion.p>

                {todo.description && !isTarget && (
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {todo.description}
                  </p>
                )}

                {/* Chips row */}
                {!isTarget && (
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
                          <Tag01Icon width={17} height={17} className="mx-1" />
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
                )}
              </div>

              {/* Workflow Category Icons */}
              {!isTarget && todo.workflowCategories.length > 0 && (
                <div className="flex min-h-8 items-center -space-x-1.5 self-center">
                  {todo.workflowCategories.slice(0, 3).map((category, i) => {
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

              {/* Done badge for target, ChevronRight for others */}
              {isTarget ? (
                <motion.span
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.4, type: "spring", stiffness: 400 }}
                  className="shrink-0 self-center rounded-full bg-success/15 px-2 py-0.5 text-xs text-success"
                >
                  Done
                </motion.span>
              ) : (
                <div className="flex h-full items-center self-center">
                  <ChevronRight
                    width={20}
                    height={20}
                    className="text-zinc-400"
                  />
                </div>
              )}

              {/* Success glow on target */}
              {isTarget && (
                <motion.div
                  className="pointer-events-none absolute inset-0 rounded-none bg-success/5"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: [0, 1, 0] }}
                  transition={{ delay: 0.15, duration: 1.0 }}
                />
              )}
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}
