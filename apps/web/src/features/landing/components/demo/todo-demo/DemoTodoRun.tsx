"use client";

import { AnimatePresence, motion } from "framer-motion";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { SparklesIcon } from "@/icons";
import {
  DEMO_TODO_WORKFLOW,
  TARGET_TODO,
  type TodoDemoPhase,
  tdEase,
} from "./todoDemoConstants";

interface DemoTodoRunProps {
  phase: TodoDemoPhase;
}

// How many tool call lines to show per phase
const TOOL_CALLS_VISIBLE: Record<string, number> = {
  run_click: 0,
  executing: 4,
};

export default function DemoTodoRun({ phase }: DemoTodoRunProps) {
  const visibleCount = TOOL_CALLS_VISIBLE[phase] ?? 0;
  const calls = DEMO_TODO_WORKFLOW.toolCalls.slice(0, visibleCount);

  return (
    <motion.div
      key="todo-run"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease: tdEase }}
      className="mx-auto w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl"
    >
      {/* Header */}
      <div className="border-b border-zinc-800 px-5 py-3.5">
        <div className="flex items-center gap-2">
          <motion.div
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 1.2, repeat: Infinity }}
          >
            <SparklesIcon className="h-4 w-4 text-primary" />
          </motion.div>
          <span className="text-sm font-medium text-zinc-300">
            Running workflow…
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-zinc-500">
          {TARGET_TODO.title}
        </p>
      </div>

      {/* Tool call lines */}
      <div className="space-y-3 px-5 py-4 min-h-[180px]">
        <AnimatePresence>
          {calls.map((call, index) => (
            <motion.div
              key={`${call.category}-${index}`}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                type: "spring",
                stiffness: 400,
                damping: 30,
                delay: index * 0.28,
              }}
              className="flex items-center gap-2.5 rounded-xl bg-zinc-800/60 px-3 py-2.5"
            >
              <div className="shrink-0">
                {getToolCategoryIcon(call.category, {
                  width: 18,
                  height: 18,
                  showBackground: false,
                })}
              </div>
              <span className="text-sm text-zinc-300">{call.message}</span>
              {/* Animated ellipsis for the last visible item */}
              {index === calls.length - 1 &&
                visibleCount < DEMO_TODO_WORKFLOW.toolCalls.length && (
                  <motion.span
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 0.9, repeat: Infinity }}
                    className="ml-auto text-xs text-zinc-600"
                  >
                    …
                  </motion.span>
                )}
              {/* Checkmark for completed items */}
              {index < calls.length - 1 && (
                <motion.span
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{
                    type: "spring",
                    stiffness: 500,
                    damping: 25,
                    delay: index * 0.28 + 0.1,
                  }}
                  className="ml-auto text-xs text-success"
                >
                  ✓
                </motion.span>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
