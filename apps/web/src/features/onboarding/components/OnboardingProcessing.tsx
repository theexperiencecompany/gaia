"use client";

import {
  Brain01Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  FilterIcon,
  type IconProps,
  Mail01Icon,
  ZapIcon,
} from "@icons";
import { AnimatePresence, m } from "motion/react";
import type { FC } from "react";
import { useEffect, useRef, useState } from "react";
import {
  STEP_BUILDING_PROFILE,
  STEP_CREATING_TODOS,
  STEP_CREATING_WORKFLOWS,
  STEP_LEARNING_STYLE,
  STEP_SCANNING_INBOX,
  STEP_TRIAGING,
} from "../constants/messages";

const SLOW_NOTICE_MS = 30_000;

interface ProcessingStep {
  icon: FC<IconProps>;
  stage: string;
  activeText: string;
}

const GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Mail01Icon,
    stage: "scanning_inbox",
    activeText: STEP_SCANNING_INBOX,
  },
  {
    icon: Brain01Icon,
    stage: "finding_profiles",
    activeText: STEP_LEARNING_STYLE,
  },
  {
    icon: FilterIcon,
    stage: "triaging",
    activeText: STEP_TRIAGING,
  },
  {
    icon: CheckListIcon,
    stage: "creating_todos",
    activeText: STEP_CREATING_TODOS,
  },
  {
    icon: ZapIcon,
    stage: "creating_workflows",
    activeText: STEP_CREATING_WORKFLOWS,
  },
];

const NO_GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Brain01Icon,
    stage: "starting",
    activeText: STEP_BUILDING_PROFILE,
  },
  {
    icon: CheckListIcon,
    stage: "creating_todos",
    activeText: STEP_CREATING_TODOS,
  },
  {
    icon: ZapIcon,
    stage: "creating_workflows",
    activeText: STEP_CREATING_WORKFLOWS,
  },
];

interface OnboardingProcessingProps {
  hasGmail: boolean;
  isIntelligenceComplete: boolean;
  intelligenceConversationId: string | null;
  onComplete: (conversationId: string) => void;
  processingProgress?: number;
  /** Map of stage name → latest backend message for that stage */
  stageMessages?: Record<string, string>;
}

export const OnboardingProcessing = ({
  hasGmail,
  isIntelligenceComplete,
  intelligenceConversationId,
  onComplete,
  processingProgress,
  stageMessages,
}: OnboardingProcessingProps) => {
  const steps = hasGmail ? GMAIL_STEPS : NO_GMAIL_STEPS;
  const completedRef = useRef(false);
  const [showSlowNotice, setShowSlowNotice] = useState(false);

  // Navigate to chat when intelligence is complete
  useEffect(() => {
    if (
      isIntelligenceComplete &&
      intelligenceConversationId &&
      !completedRef.current
    ) {
      completedRef.current = true;
      onComplete(intelligenceConversationId);
    }
  }, [isIntelligenceComplete, intelligenceConversationId, onComplete]);

  // Show "taking longer" notice after 30s
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!completedRef.current) {
        setShowSlowNotice(true);
      }
    }, SLOW_NOTICE_MS);

    return () => clearTimeout(timer);
  }, []);

  // Determine active step from which stages have been seen, not from progress %
  const activeStepIndex = (() => {
    if (!stageMessages) return 0;
    let lastSeenIndex = -1;
    for (let i = 0; i < steps.length; i++) {
      if (stageMessages[steps[i].stage]) {
        lastSeenIndex = i;
      }
    }
    // The active step is the one after the last completed, or 0 if none seen
    return Math.min(lastSeenIndex + 1, steps.length - 1);
  })();

  return (
    <m.div
      className="mt-3 flex flex-col gap-3 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.19, 1, 0.22, 1] }}
    >
      {isIntelligenceComplete && (
        <p className="sr-only" aria-live="assertive" aria-atomic="true">
          Setup complete. You can now start using GAIA.
        </p>
      )}

      <div className="flex flex-col gap-2.5" aria-live="polite">
        {steps.map((step, i) => {
          const Icon = step.icon;
          const isDone = i < activeStepIndex;
          const isActive = i === activeStepIndex;
          const liveMessage = stageMessages?.[step.stage];
          const displayText =
            (isDone || isActive) && liveMessage ? liveMessage : step.activeText;

          return (
            <m.div
              key={step.stage}
              className="flex items-center gap-3"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: i * 0.12,
                duration: 0.3,
                ease: [0.19, 1, 0.22, 1],
              }}
            >
              <div className="relative size-4 shrink-0">
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
              <span
                className={
                  isDone
                    ? "text-sm text-zinc-300"
                    : isActive
                      ? "text-sm font-medium text-zinc-200"
                      : "text-sm text-zinc-500"
                }
              >
                {displayText}
              </span>
            </m.div>
          );
        })}
      </div>

      <AnimatePresence>
        {showSlowNotice && !isIntelligenceComplete && (
          <m.p
            className="text-xs text-zinc-500"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
          >
            Taking a bit longer than usual, hang tight.
          </m.p>
        )}
      </AnimatePresence>

      <m.div className="mt-3 h-0.5 w-full overflow-hidden rounded-full bg-zinc-700">
        <m.div
          className="h-full rounded-full bg-primary"
          animate={{ width: `${processingProgress ?? 0}%` }}
          transition={{ duration: 0.8, ease: [0.19, 1, 0.22, 1] }}
        />
      </m.div>
    </m.div>
  );
};
