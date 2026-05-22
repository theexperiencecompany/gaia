"use client";

import { useEffect, useRef } from "react";

import {
  ANALYTICS_EVENTS,
  trackEvent,
  trackOnboardingComplete,
  trackOnboardingStep,
} from "@/lib/analytics";

import { FIELD_NAMES, questions } from "../constants";
import type { OnboardingState } from "../state/types";

export function useOnboardingAnalytics(state: OnboardingState): void {
  const startedRef = useRef(false);
  const prevQuestionIndexRef = useRef<number | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
      has_saved_state:
        state.questionIndex > 0 || Object.keys(state.responses).length > 0,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const prev = prevQuestionIndexRef.current;
    const curr = state.questionIndex;
    prevQuestionIndexRef.current = curr;

    if (prev == null) return;
    if (curr === prev) return;
    if (curr <= 0) return;

    const answeredIndex = curr - 1;
    if (answeredIndex < 0 || answeredIndex >= questions.length) return;

    const q = questions[answeredIndex];
    const value = state.responses[q.fieldName];
    if (value == null) return;

    trackOnboardingStep(answeredIndex + 1, q.fieldName, {
      response_value: value,
      question_id: q.id,
    });
  }, [state.questionIndex, state.responses]);

  useEffect(() => {
    if (completedRef.current) return;
    if (!state.server?.first_message_conversation_id) return;
    completedRef.current = true;
    trackOnboardingComplete({
      profession: state.responses[FIELD_NAMES.PROFESSION],
      totalSteps: questions.length + 1,
    });
  }, [state.server?.first_message_conversation_id, state.responses]);
}
