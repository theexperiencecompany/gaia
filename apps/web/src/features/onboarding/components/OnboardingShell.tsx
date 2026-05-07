/**
 * Full-screen layout wrapper for the onboarding page. Three regions: top
 * progress bar, scrollable content (caller-supplied children), and an
 * optional pinned composer at the bottom. Auto-scrolls the content region
 * to bottom whenever stage- or content-bearing state changes.
 */

"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef } from "react";
import { getProgress, PROGRESS_TOTAL_STEPS } from "../state/derive";
import type { OnboardingState, Stage } from "../state/types";
import { OnboardingProgress } from "./OnboardingProgress";

interface OnboardingShellProps {
  state: OnboardingState;
  stage: Stage;
  onRestart: () => void;
  children: ReactNode;
  composer?: ReactNode;
}

/**
 * Single string fingerprint of "what's on screen". Used as a useEffect dep so
 * scroll-to-bottom fires once per content change instead of needing 7 deps.
 */
function getContentFingerprint(state: OnboardingState, stage: Stage): string {
  const b = state.server;
  return [
    stage,
    state.questionIndex,
    state.progressMessage ?? "",
    b?.writing_style?.style_summary ?? "",
    b?.onboarding_todos?.length ?? 0,
    b?.suggested_workflows?.length ?? 0,
    b?.first_message_conversation_id ?? "",
    state.todoExecutionMessage ?? "",
  ].join("|");
}

export function OnboardingShell({
  state,
  stage,
  onRestart,
  children,
  composer,
}: OnboardingShellProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const progressStep = getProgress(state, stage);
  const fingerprint = useMemo(
    () => getContentFingerprint(state, stage),
    [state, stage],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [fingerprint]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-primary-bg backdrop-blur-2xl">
      <OnboardingProgress
        currentStep={progressStep}
        totalSteps={PROGRESS_TOTAL_STEPS}
        onRestart={onRestart}
        isRestarting={state.isRestarting}
      />

      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-4 pt-20 pb-10"
      >
        <div className="relative mx-auto max-w-2xl">{children}</div>
      </div>

      {composer && (
        <div className="relative z-10 mx-auto w-full max-w-lg pb-3">
          {composer}
        </div>
      )}
    </div>
  );
}
