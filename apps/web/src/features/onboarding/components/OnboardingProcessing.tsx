/**
 * Stage-by-stage checklist of the backend personalization pipeline. Each
 * step shows a spinner while active, a check once its corresponding
 * `OnboardingStage` lands in `completedStages`, and a 30s "still working"
 * notice if everything stalls. Steps differ for the Gmail vs no-Gmail
 * branch — the no-Gmail branch is reordered to match actual emit order.
 */

"use client";

import {
  AiBrain01Icon,
  Brain01Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  FilterIcon,
  type IconProps,
  Loading03Icon,
  Mail01Icon,
  ZapIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
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
  // Stages contributing this step's live sub-message, in priority order.
  progressFrom: readonly OnboardingStage[];
}

const GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Mail01Icon,
    stage: "inbox_scanning",
    activeText: STEP_SCANNING_INBOX,
    progressFrom: ["inbox_scanning"],
  },
  {
    icon: AiBrain01Icon,
    stage: "writing_style_ready",
    activeText: STEP_LEARNING_STYLE,
    progressFrom: ["writing_style_progress"],
  },
  {
    icon: FilterIcon,
    stage: "triage_ready",
    activeText: STEP_TRIAGING,
    progressFrom: ["triage_analyzing"],
  },
  {
    icon: CheckListIcon,
    stage: "todos_ready",
    activeText: STEP_CREATING_TODOS,
    progressFrom: ["todos_creating"],
  },
  {
    icon: ZapIcon,
    stage: "workflows_ready",
    activeText: STEP_CREATING_WORKFLOWS,
    progressFrom: ["workflows_creating"],
  },
];

// Order must match backend emit order for the no-Gmail path: todos, workflows, holo.
const NO_GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: CheckListIcon,
    stage: "todos_ready",
    activeText: STEP_CREATING_TODOS,
    progressFrom: ["todos_creating"],
  },
  {
    icon: ZapIcon,
    stage: "workflows_ready",
    activeText: STEP_CREATING_WORKFLOWS,
    progressFrom: ["workflows_creating"],
  },
  {
    icon: Brain01Icon,
    stage: "holo_ready",
    activeText: STEP_BUILDING_PROFILE,
    progressFrom: [],
  },
];

interface OnboardingProcessingProps {
  hasGmail: boolean;
  completedStages?: Set<OnboardingStage>;
  progressByStage?: Partial<Record<OnboardingStage, string>>;
}

// Stages that prove the inbox scan finished. writing_style_ready excluded:
// it uses a separate 50-email fetch, not the full inbox scan.
const STAGES_AFTER_INBOX_SCAN: OnboardingStage[] = [
  "triage_ready",
  "social_profiles_ready",
  "todos_ready",
  "workflows_ready",
  "complete",
];

function pickProgressForStep(
  step: ProcessingStep,
  progressByStage: Partial<Record<OnboardingStage, string>> | undefined,
): string | undefined {
  if (!progressByStage) return undefined;
  for (const stage of step.progressFrom) {
    const value = progressByStage[stage];
    if (value) return value;
  }
  return undefined;
}

function OnboardingProcessingImpl({
  hasGmail,
  completedStages,
  progressByStage,
}: OnboardingProcessingProps) {
  const steps = hasGmail ? GMAIL_STEPS : NO_GMAIL_STEPS;
  const [showSlowNotice, setShowSlowNotice] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowSlowNotice(true), SLOW_NOTICE_MS);
    return () => clearTimeout(timer);
  }, []);

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
      className="mt-3 flex w-[28rem] flex-col gap-3 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE_OUT_QUART }}
    >
      <div className="flex flex-col gap-2.5" aria-live="polite">
        {steps.map((step, i) => {
          const Icon = step.icon;
          const isDone = isStepDone(i);
          const isActive = i === activeStepIndex && !isDone;
          const liveMessage = isActive
            ? pickProgressForStep(step, progressByStage)
            : undefined;

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
                        className="text-xs text-zinc-500 tabular-nums truncate"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        title={liveMessage}
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
                    <Loading03Icon className="size-4 text-primary animate-spin" />
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
