"use client";

import {
  Brain01Icon,
  CheckListIcon,
  FilterIcon,
  type IconProps,
  Mail01Icon,
  ZapIcon,
} from "@icons";
import { m } from "motion/react";
import { useRouter } from "next/navigation";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/lib/api";

const TIMEOUT_MS = 90_000;

interface ProcessingStep {
  icon: FC<IconProps>;
  stage: string;
  activeText: string;
}

const GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Mail01Icon,
    stage: "scanning_inbox",
    activeText: "Scanning your inbox",
  },
  {
    icon: FilterIcon,
    stage: "triaging",
    activeText: "Triaging by importance",
  },
  {
    icon: CheckListIcon,
    stage: "creating_todos",
    activeText: "Creating action items",
  },
  {
    icon: Brain01Icon,
    stage: "finding_profiles",
    activeText: "Learning your style",
  },
  {
    icon: ZapIcon,
    stage: "creating_workflows",
    activeText: "Setting up automations",
  },
];

const NO_GMAIL_STEPS: ProcessingStep[] = [
  {
    icon: Brain01Icon,
    stage: "starting",
    activeText: "Building your profile",
  },
  {
    icon: ZapIcon,
    stage: "creating_workflows",
    activeText: "Setting up automations",
  },
];

interface OnboardingProcessingProps {
  hasGmail: boolean;
  isIntelligenceComplete: boolean;
  intelligenceConversationId: string | null;
  onComplete: (conversationId: string) => void;
}

export const OnboardingProcessing = ({
  hasGmail,
  isIntelligenceComplete,
  intelligenceConversationId,
  onComplete,
}: OnboardingProcessingProps) => {
  const steps = hasGmail ? GMAIL_STEPS : NO_GMAIL_STEPS;
  const [timedOut, setTimedOut] = useState(false);
  const router = useRouter();
  const completedRef = useRef(false);

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

  // Timeout — if intelligence pipeline hasn't completed in 90s, show fallback
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!completedRef.current) {
        setTimedOut(true);
      }
    }, TIMEOUT_MS);

    return () => clearTimeout(timer);
  }, []);

  const handleSkipToChat = useCallback(async () => {
    completedRef.current = true;
    try {
      await apiService.post("/onboarding/phase", { phase: "getting_started" });
    } catch {
      // non-blocking
    }
    router.push("/c");
  }, [router]);

  return (
    <m.div
      className="mt-3 ml-[43px] flex flex-col gap-3 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.19, 1, 0.22, 1] }}
    >
      {timedOut ? (
        <m.div
          className="flex flex-col gap-3"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
        >
          <span className="text-sm text-zinc-400">
            This is taking longer than expected. Let&apos;s get you started —
            I&apos;ll finish setting things up in the background.
          </span>
          <button
            type="button"
            onClick={handleSkipToChat}
            className="cursor-pointer rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            Get started
          </button>
        </m.div>
      ) : (
        <>
          <div className="flex flex-col gap-2.5">
            {steps.map((step, i) => {
              const Icon = step.icon;
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
                  <Icon className="size-4 text-zinc-500" />
                  <span className="text-sm text-zinc-500">
                    {step.activeText}
                  </span>
                </m.div>
              );
            })}
          </div>

          <div className="h-0.5 w-full overflow-hidden rounded-full bg-zinc-700">
            <m.div
              className="h-full rounded-full bg-primary"
              animate={{ width: ["0%", "85%", "85%"] }}
              transition={{
                duration: 3,
                ease: "easeOut",
                times: [0, 0.7, 1],
              }}
            />
          </div>
        </>
      )}
    </m.div>
  );
};
