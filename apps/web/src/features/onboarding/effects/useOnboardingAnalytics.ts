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
// Each is fired on *entering* the stage after it, which is the only moment the
// previous stage is provably cleared.
const STAGE_STEPS: Partial<Record<Stage, { step: number; name: string }>> = {
  paidReveal: { step: questions.length + 1, name: "payment" },
  platformPick: { step: questions.length + 2, name: "paid_reveal" },
  chat: { step: questions.length + 3, name: "platform_pick" },
};

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
  hydrated: boolean,
): void {
  const startedRef = useRef(false);
  const prevQuestionIndexRef = useRef<number | null>(null);
  const trackedStagesRef = useRef(new Set<Stage>());

  useEffect(() => {
    // Waits for the persisted state to be restored: fired any earlier, every
    // resumed session reports `has_saved_state: false`, because the hydrate
    // dispatch has not been rendered yet.
    if (!hydrated || startedRef.current) return;
    startedRef.current = true;
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
      has_saved_state: state.questionIndex > 0,
    });
  }, [hydrated, state.questionIndex]);

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

  const { connectedPlatform } = state;
  useEffect(() => {
    const entry = STAGE_STEPS[stage];
    if (!entry || trackedStagesRef.current.has(stage)) return;
    trackedStagesRef.current.add(stage);
    trackOnboardingStep(
      entry.step,
      entry.name,
      // Which way the platform pick was cleared is the whole question that
      // step answers, so it rides along rather than needing a second event.
      stage === "chat"
        ? {
            connected: connectedPlatform !== null,
            platform: connectedPlatform,
          }
        : undefined,
    );
  }, [stage, connectedPlatform]);

  // A restart replays the whole funnel, so the once-per-stage guards have to
  // reopen with it — otherwise the second run reports no steps at all.
  const { isRestarting } = state;
  useEffect(() => {
    if (!isRestarting) return;
    // Only the stage guards: the question cursor is reset to 0 by the same
    // action, and the effect above already tracks that move without firing.
    trackedStagesRef.current.clear();
  }, [isRestarting]);
}
