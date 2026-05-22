/**
 * Full-screen layout wrapper for the onboarding page. Three regions: top
 * progress bar, scrollable content (caller-supplied children), and an
 * optional pinned composer at the bottom. Auto-scrolls the content region
 * to bottom whenever stage- or content-bearing state changes.
 */

"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import { getProgress, PROGRESS_TOTAL_STEPS } from "../state/derive";
import type { OnboardingState, Stage } from "../state/types";
import { OnboardingProgress } from "./OnboardingProgress";

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

function getContentFingerprint(state: OnboardingState, stage: Stage): string {
  const b = state.server;
  const progress = Object.values(state.progressByStage).join("");
  return [
    stage,
    state.questionIndex,
    progress,
    state.completedStages.size,
    state.ackedWritingStyle ? 1 : 0,
    state.ackedTodos ? 1 : 0,
    state.workflowsConfirmed ? 1 : 0,
    state.platformsConfirmed ? 1 : 0,
    state.connectedPlatform ?? "",
    b?.writing_style?.style_summary ?? "",
    b?.onboarding_todos?.length ?? 0,
    b?.suggested_workflows?.length ?? 0,
    b?.first_message_conversation_id ?? "",
    state.todoExecutionMessage ?? "",
    Object.keys(state.clarifyAnswers).length,
    state.clarifySubmitted ? 1 : 0,
  ].join("|");
}

const COMPOSER_GUTTER_PX = 24;
const BOTTOM_BLUR_PX = 96;

export function OnboardingShell({
  state,
  stage,
  onRestart,
  children,
  composer,
}: OnboardingShellProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const [composerHeight, setComposerHeight] = useState(0);
  const progressStep = getProgress(state, stage);
  const fingerprint = useMemo(
    () => getContentFingerprint(state, stage),
    [state, stage],
  );

  const hasComposer = !!composer;
  useEffect(() => {
    const el = composerRef.current;
    if (!el) {
      setComposerHeight(0);
      return;
    }
    const update = () => setComposerHeight(el.getBoundingClientRect().height);
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasComposer, stage]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [fingerprint, composerHeight]);

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
        <div
          className="relative mx-auto w-full max-w-3xl"
          style={{
            paddingBottom:
              Math.max(composer ? composerHeight : 0, BOTTOM_BLUR_PX) +
              COMPOSER_GUTTER_PX,
          }}
        >
          {children}
        </div>
      </div>

      <BlurStack
        className="pointer-events-none fixed top-0 right-0 left-0 z-20 h-24"
        config={TOP_BLUR_CONFIG}
      />
      <BlurStack className="pointer-events-none fixed right-0 bottom-0 left-0 z-20 h-24" />

      {composer && (
        <div
          ref={composerRef}
          className={
            stage === "clarify"
              ? "fixed inset-x-0 bottom-0 z-30 mx-auto w-full max-w-xl pb-3"
              : "fixed inset-x-0 bottom-0 z-30 mx-auto w-full max-w-lg pb-3"
          }
        >
          {composer}
        </div>
      )}
    </div>
  );
}
