"use client";

import { Button } from "@heroui/button";
import { PlayIcon, ZapIcon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  DEMO_TODO_WORKFLOW,
  TARGET_TODO,
  type TodoDemoPhase,
  tdEase,
} from "./todoDemoConstants";

interface DemoTodoWorkflowProps {
  phase: TodoDemoPhase;
}

const STEPS_PER_PHASE: Record<string, number> = {
  workflow_appear: 1,
  workflow_ready: 4,
  run_click: 4,
};

export default function DemoTodoWorkflow({ phase }: DemoTodoWorkflowProps) {
  const visibleCount = STEPS_PER_PHASE[phase] ?? 1;
  const showRunButton = ["workflow_ready", "run_click"].includes(phase);
  const isRunPressed = phase === "run_click";
  const steps = DEMO_TODO_WORKFLOW.steps.slice(0, visibleCount);

  return (
    <m.div
      key="todo-workflow"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ type: "spring", stiffness: 340, damping: 28 }}
      style={{ willChange: "transform, opacity" }}
      className="mx-auto w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl"
    >
      {/* Header: target todo context */}
      <div className="border-b border-zinc-800 px-5 py-3.5">
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <ZapIcon width={13} height={13} />
          <span>Suggested Workflow for</span>
        </div>
        <p className="mt-0.5 text-sm font-medium text-zinc-200">
          {TARGET_TODO.title}
        </p>
      </div>

      {/* Steps */}
      <div className="space-y-0 px-5 py-4">
        <AnimatePresence>
          {steps.map((step, index) => (
            <m.div
              key={step.id}
              initial={{ opacity: 0, y: 10, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{
                type: "spring",
                stiffness: 420,
                damping: 32,
                delay: index * 0.15,
              }}
              className="relative flex items-start gap-3 pb-4 last:pb-0"
            >
              {/* Connector line */}
              {index < steps.length - 1 && (
                <div className="absolute left-[13px] top-7 h-full w-px bg-zinc-700/60" />
              )}

              {/* Step dot */}
              <div className="relative z-10 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border border-primary bg-primary/10">
                <span className="text-[10px] font-semibold text-primary">
                  {index + 1}
                </span>
              </div>

              {/* Content */}
              <div className="flex-1 pt-0.5">
                <div className="flex items-center gap-1.5">
                  <div className="shrink-0">
                    {getToolCategoryIcon(step.category, {
                      width: 14,
                      height: 14,
                      showBackground: false,
                    })}
                  </div>
                  <p className="text-sm font-medium text-zinc-200">
                    {step.title}
                  </p>
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {step.description}
                </p>
              </div>
            </m.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Footer: Run button */}
      <AnimatePresence>
        {showRunButton && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: tdEase }}
            className="border-t border-zinc-800 px-5 py-3"
          >
            <m.div
              animate={isRunPressed ? { scale: 0.97 } : { scale: 1 }}
              transition={{ duration: 0.12 }}
            >
              <Button
                color="success"
                variant="flat"
                size="sm"
                fullWidth
                endContent={<PlayIcon className="h-4 w-4" />}
                className={isRunPressed ? "ring-2 ring-success/50" : ""}
              >
                Run Workflow
              </Button>
            </m.div>
          </m.div>
        )}
      </AnimatePresence>
    </m.div>
  );
}
