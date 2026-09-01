"use client";

import { useEffect, useRef } from "react";

import {
  ANALYTICS_EVENTS,
  trackEvent,
  trackOnboardingStep,
} from "@/lib/analytics";

import { questions } from "../constants";
import type { OnboardingState, Stage } from "../state/types";

// Step numbers continue past the two questions so the funnel reads in order.
const PAYMENT_STAGE_STEP = questions.length + 1;
const PLATFORM_STAGE_STEP = questions.length + 2;

/**
 * Onboarding funnel events. Never sends answer values — professions and
 * needs are user-attributable, so only the question answered is tracked.
 *
 * Payment success itself is server-owned (the Dodo webhook); the only
 * payment event here marks that the *UI* stage was cleared.
 * `onboarding:completed` is emitted by the API when the submission lands.
 */
export function useOnboardingAnalytics(
  state: OnboardingState,
  stage: Stage,
): void {
  const startedRef = useRef(false);
  const prevQuestionIndexRef = useRef<number | null>(null);
  const trackedStagesRef = useRef(new Set<Stage>());

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
      has_saved_state: state.questionIndex > 0,
    });
    // Fires once per mount; the resumed-state property is a snapshot of that moment.
  }, [state.questionIndex]);

  useEffect(() => {
    const prev = prevQuestionIndexRef.current;
    const curr = state.questionIndex;
    prevQuestionIndexRef.current = curr;

    if (prev == null || curr === prev || curr <= 0) return;

    const answeredIndex = curr - 1;
    if (answeredIndex >= questions.length) return;

    const q = questions[answeredIndex];
    trackOnboardingStep(answeredIndex + 1, q.fieldName, { question_id: q.id });
  }, [state.questionIndex]);

  useEffect(() => {
    if (stage !== "greeting" && stage !== "chat") return;
    // Reaching `greeting` means the paid-reveal stage was cleared; reaching
    // `chat` means the platform pick was.
    const step =
      stage === "greeting" ? PAYMENT_STAGE_STEP : PLATFORM_STAGE_STEP;
    const name =
      stage === "greeting" ? "payment_stage_completed" : "platform_pick";
    if (trackedStagesRef.current.has(stage)) return;
    trackedStagesRef.current.add(stage);
    trackOnboardingStep(step, name);
  }, [stage]);
}
