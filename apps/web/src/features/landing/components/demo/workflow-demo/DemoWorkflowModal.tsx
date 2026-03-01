"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Input, Textarea } from "@heroui/react";
import { Skeleton } from "@heroui/skeleton";
import { Switch } from "@heroui/switch";
import { AnimatePresence, m } from "motion/react";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import DemoTriggerTabs from "./DemoTriggerTabs";
import {
  DEMO_WORKFLOW,
  type WorkflowDemoPhase,
  wfTx,
} from "./workflowDemoConstants";

interface DemoWorkflowModalProps {
  phase: WorkflowDemoPhase;
}

export default function DemoWorkflowModal({ phase }: DemoWorkflowModalProps) {
  const showModal = [
    "modal_appear",
    "trigger_config",
    "schedule_set",
    "steps_generating",
  ].includes(phase);

  const showTrigger = [
    "trigger_config",
    "schedule_set",
    "steps_generating",
  ].includes(phase);

  const showTriggerContent = ["schedule_set", "steps_generating"].includes(
    phase,
  );
  const showSteps = phase === "steps_generating";

  const activeTab =
    phase === "steps_generating" ? ("trigger" as const) : ("schedule" as const);
  const triggerType =
    phase === "steps_generating" ? ("trigger" as const) : ("schedule" as const);
  const stepsVisible = showSteps ? DEMO_WORKFLOW.steps.length : 0;

  return (
    <AnimatePresence>
      {showModal && (
        <m.div
          key="wf-modal"
          initial={{ opacity: 0, scale: 0.92, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ type: "spring", stiffness: 350, damping: 30 }}
          style={{ willChange: "transform, opacity" }}
          className="absolute inset-x-12 top-1/2 z-20 mx-auto max-w-5xl h-[560px] -translate-y-1/2 overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl flex flex-col"
        >
          {/* Top scrollable content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            <div className="flex h-full min-h-0 items-start gap-8 p-6">
              {/* Left panel */}
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-2">
                  {/* Title */}
                  <m.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.15, ...wfTx }}
                  >
                    <Input
                      value={DEMO_WORKFLOW.title}
                      variant="underlined"
                      placeholder="Workflow title"
                      readOnly
                      classNames={{
                        input: "font-medium! text-4xl",
                        inputWrapper: "px-0",
                      }}
                    />
                  </m.div>

                  {/* Description */}
                  <m.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.3, ...wfTx }}
                  >
                    <Textarea
                      value={DEMO_WORKFLOW.description}
                      variant="underlined"
                      placeholder="What should this workflow do?"
                      minRows={3}
                      readOnly
                      classNames={{
                        input: "text-sm mb-1",
                        inputWrapper: "px-0",
                      }}
                    />
                  </m.div>

                  {/* Divider */}
                  <div className="border-t border-zinc-800" />

                  {/* Trigger section */}
                  <DemoTriggerTabs
                    activeTab={activeTab}
                    showContent={showTriggerContent}
                    triggerType={triggerType}
                  />
                </div>
              </div>

              {/* Right panel: steps */}
              <div className="flex min-h-0 w-80 flex-col">
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-zinc-500">
                      Steps
                    </span>
                    <AnimatePresence>
                      {showSteps && (
                        <m.span
                          key="step-count"
                          initial={{ opacity: 0, scale: 0.8 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{
                            type: "spring",
                            stiffness: 500,
                            damping: 25,
                          }}
                          className="rounded-full bg-primary/15 px-1.5 py-0.5 text-xs text-primary"
                        >
                          {DEMO_WORKFLOW.steps.length} steps
                        </m.span>
                      )}
                    </AnimatePresence>
                  </div>

                  {showSteps ? (
                    <WorkflowSteps
                      steps={DEMO_WORKFLOW.steps.slice(0, stepsVisible)}
                    />
                  ) : showTrigger ? (
                    <div className="space-y-4">
                      <Skeleton className="h-16 rounded-xl" />
                      <Skeleton className="h-16 rounded-xl" />
                      <Skeleton className="h-16 rounded-xl" />
                      <Skeleton className="h-14 rounded-xl" />
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-6">
                      <p className="text-sm text-zinc-600">
                        Steps will be generated
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Fixed footer at bottom */}
          <div className="border-t border-zinc-800 px-6 py-3 bg-zinc-900">
            <div className="flex items-center justify-between">
              {/* Left side: Activation switch */}
              <div className="flex items-center gap-2">
                <Switch
                  size="sm"
                  isSelected={true}
                  aria-label="Workflow active"
                />
                <span className="text-xs text-zinc-400">Active</span>
              </div>

              {/* Right side: Cancel and Create buttons */}
              <div className="flex items-center gap-3">
                <Button variant="flat" size="md">
                  Cancel
                </Button>
                <Button
                  color="primary"
                  size="md"
                  endContent={<Kbd keys={["command", "enter"]} />}
                >
                  Create Workflow
                </Button>
              </div>
            </div>
          </div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
