/**
 * Full-screen layout wrapper for the onboarding page. Three regions: top
 * progress bar, scrollable content (caller-supplied children), and an
 * optional pinned composer at the bottom. Auto-scrolls the content region
 * to bottom whenever stage- or content-bearing state changes.
 */

"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef } from "react";
import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import { getProgress, PROGRESS_TOTAL_STEPS } from "../state/derive";
import type { OnboardingState, Stage } from "../state/types";
import { OnboardingProgress } from "./OnboardingProgress";

// Heavy-blur-at-top config — mirror of the default heavy-at-bottom stack.
const TOP_BLUR_CONFIG: BlurLayer[] = [
  { blur: 0.5, maskStops: [62.5, 75, 87.5, 100], zIndex: 1 },
  { blur: 1, maskStops: [50, 62.5, 75, 87.5], zIndex: 2 },
  { blur: 2, maskStops: [37.5, 50, 62.5, 75], zIndex: 3 },
  { blur: 4, maskStops: [25, 37.5, 50, 62.5], zIndex: 4 },
  { blur: 8, maskStops: [12.5, 25, 37.5, 50], zIndex: 5 },
  { blur: 16, maskStops: [0, 12.5, 25, 37.5], zIndex: 6 },
  { blur: 32, maskStops: [0, 0, 12.5, 25], zIndex: 7 },
  { blur: 64, maskStops: [0, 0, 0, 12.5], zIndex: 8 },
];

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
  // Concat every active progress slot — any change to any stage's status_text
  // should re-trigger the scroll-to-bottom effect.
  const progress = Object.values(state.progressByStage).join("");
  return [
    stage,
    state.questionIndex,
    progress,
    state.completedStages.size,
    state.ackedWritingStyle ? 1 : 0,
    state.ackedTodos ? 1 : 0,
    state.workflowsConfirmed ? 1 : 0,
    state.connectedPlatform ?? "",
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
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 bg-center bg-cover opacity-40"
        style={{
          backgroundImage: "url('/images/wallpapers/bands_gradient_black.png')",
        }}
      />
      <OnboardingProgress
        currentStep={progressStep}
        totalSteps={PROGRESS_TOTAL_STEPS}
        onRestart={onRestart}
        isRestarting={state.isRestarting}
      />

      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-4 pt-20"
      >
        <div className="relative mx-auto max-w-2xl pb-48">{children}</div>
      </div>

      <BlurStack
        className="pointer-events-none fixed top-0 right-0 left-0 z-20 h-24"
        config={TOP_BLUR_CONFIG}
      />
      <BlurStack className="pointer-events-none fixed right-0 bottom-0 left-0 z-20 h-24" />

      {composer && (
        <div className="fixed inset-x-0 bottom-0 z-30 mx-auto w-full max-w-lg pb-3">
          {composer}
        </div>
      )}
    </div>
  );
}
