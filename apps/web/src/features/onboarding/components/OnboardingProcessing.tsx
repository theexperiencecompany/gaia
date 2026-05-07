/**
 * Stage-by-stage checklist of the backend personalization pipeline. Each
 * step shows a spinner while active, a check once its corresponding
 * `OnboardingStage` lands in `completedStages`, and a 30s "still working"
 * notice if everything stalls. Steps differ for the Gmail vs no-Gmail
 * branch — the no-Gmail branch is reordered to match actual emit order.
 */

"use client";

import {
  Brain01Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  FilterIcon,
  type IconProps,
  Loading03Icon,
  Mail01Icon,
  ZapIcon,
} from "@icons";
import { AnimatePresence, m } from "motion/react";
import { type FC, memo, useEffect, useState } from "react";
import {
  STEP_BUILDING_PROFILE,
  STEP_CREATING_TODOS,
  STEP_CREATING_WORKFLOWS,
  STEP_LEARNING_STYLE,
  STEP_SCANNING_INBOX,
  STEP_TRIAGING,
} from "../constants/messages";
import { EASE_OUT_QUART } from "../constants/motion";
import type { OnboardingStage } from "../types/websocket";

const SLOW_NOTICE_MS = 30_000;

interface ProcessingStep {
  icon: FC<IconProps>;
  stage: OnboardingStage;
  activeText: string;
}

const GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Mail01Icon,
    stage: "inbox_scanning",
    activeText: STEP_SCANNING_INBOX,
  },
  {
    icon: Brain01Icon,
    stage: "writing_style_ready",
    activeText: STEP_LEARNING_STYLE,
  },
  {
    icon: FilterIcon,
    stage: "triage_ready",
    activeText: STEP_TRIAGING,
  },
  {
    icon: CheckListIcon,
    stage: "todos_ready",
    activeText: STEP_CREATING_TODOS,
  },
  {
    icon: ZapIcon,
    stage: "workflows_ready",
    activeText: STEP_CREATING_WORKFLOWS,
  },
];

// Ordered to match the actual backend emission order in the no-Gmail path:
// focus-based todos fire first (fast LLM call), then workflows, then the
// holo card (phrase + bio + RAG + persist, slowest).
const NO_GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: CheckListIcon,
    stage: "todos_ready",
    activeText: STEP_CREATING_TODOS,
  },
  {
    icon: ZapIcon,
    stage: "workflows_ready",
    activeText: STEP_CREATING_WORKFLOWS,
  },
  {
    icon: Brain01Icon,
    stage: "holo_ready",
    activeText: STEP_BUILDING_PROFILE,
  },
];

interface OnboardingProcessingProps {
  hasGmail: boolean;
  /** Stages that have received a completion event from the backend */
  completedStages?: Set<OnboardingStage>;
  /** Latest backend-emitted status_text — surfaced under the active step */
  statusMessage?: string | null;
}

// Stages whose `inbox_scanning` step is genuinely complete. Writing-style
// uses an independent 50-sent-email fetch so it firing tells us nothing
// about the 500-email inbox scan — exclude it.
const STAGES_AFTER_INBOX_SCAN: OnboardingStage[] = [
  "triage_ready",
  "social_profiles_ready",
  "todos_ready",
  "workflows_ready",
  "complete",
];

function OnboardingProcessingImpl({
  hasGmail,
  completedStages,
  statusMessage,
}: OnboardingProcessingProps) {
  const steps = hasGmail ? GMAIL_STEPS : NO_GMAIL_STEPS;
  const [showSlowNotice, setShowSlowNotice] = useState(false);

  // Show "taking longer" notice after 30s
  useEffect(() => {
    const timer = setTimeout(() => setShowSlowNotice(true), SLOW_NOTICE_MS);
    return () => clearTimeout(timer);
  }, []);

  // Per-step completion: each step is marked done only when ITS own stage
  // has fired. `inbox_scanning` is a repeating stage that never emits its
  // own completion — it is considered done only when a stage that genuinely
  // depends on the inbox fetch has fired (NOT writing_style_ready, which
  // uses a separate 50-sent-email fetch and finishes long before the 500-
  // email inbox scan).
  const isStepDone = (i: number): boolean => {
    const step = steps[i];
    if (step.stage === "inbox_scanning") {
      return STAGES_AFTER_INBOX_SCAN.some((s) => completedStages?.has(s));
    }
    return completedStages?.has(step.stage) ?? false;
  };

  const activeStepIndex = (() => {
    for (let i = 0; i < steps.length; i++) {
      if (!isStepDone(i)) return i;
    }
    return steps.length - 1;
  })();

  return (
    <m.div
      className="mt-3 flex flex-col gap-3 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl w-96"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE_OUT_QUART }}
    >
      <div className="flex flex-col gap-2.5" aria-live="polite">
        {steps.map((step, i) => {
          const Icon = step.icon;
          const isDone = isStepDone(i);
          const isActive = i === activeStepIndex && !isDone;
          // Surface the backend's latest status_text under the active step
          // — every stage emits one, so the same field works uniformly.
          const liveMessage =
            isActive && statusMessage ? statusMessage : undefined;

          return (
            <m.div
              key={step.stage}
              className="flex items-center gap-3 justify-between"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: i * 0.12,
                duration: 0.3,
                ease: EASE_OUT_QUART,
              }}
            >
              <div className="relative size-4 shrink-0 self-start mt-0.5">
                <AnimatePresence mode="wait">
                  {isDone ? (
                    <m.div
                      key="check"
                      initial={{ scale: 0, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="absolute inset-0"
                    >
                      <CheckmarkCircle02Icon className="size-4 text-emerald-500" />
                    </m.div>
                  ) : (
                    <m.div
                      key="icon"
                      initial={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0, opacity: 0 }}
                      transition={{ duration: 0.15 }}
                      className="absolute inset-0"
                    >
                      <Icon
                        className={
                          isActive
                            ? "size-4 text-primary animate-pulse"
                            : "size-4 text-zinc-500"
                        }
                      />
                    </m.div>
                  )}
                </AnimatePresence>
              </div>
              <div className="flex-1 flex flex-col gap-0.5 min-w-0">
                <span
                  className={
                    isDone
                      ? "text-sm text-zinc-300"
                      : isActive
                        ? "text-sm font-medium text-zinc-200"
                        : "text-sm text-zinc-500"
                  }
                >
                  {step.activeText}
                </span>
                <AnimatePresence>
                  {isActive &&
                    liveMessage &&
                    liveMessage !== step.activeText && (
                      <m.p
                        key="sub-message"
                        className="text-xs text-zinc-500 tabular-nums"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                      >
                        {liveMessage}
                      </m.p>
                    )}
                </AnimatePresence>
              </div>
              <AnimatePresence>
                {isActive && (
                  <m.div
                    key="spinner"
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.8 }}
                    transition={{ duration: 0.2 }}
                    className="shrink-0"
                  >
                    <Loading03Icon className="size-4 text-zinc-500 animate-spin" />
                  </m.div>
                )}
              </AnimatePresence>
            </m.div>
          );
        })}
      </div>

      <AnimatePresence>
        {showSlowNotice && (
          <m.p
            className="text-xs text-zinc-500"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
          >
            Still working on it. This may take another minute or two.
          </m.p>
        )}
      </AnimatePresence>
    </m.div>
  );
}

export const OnboardingProcessing = memo(OnboardingProcessingImpl);
