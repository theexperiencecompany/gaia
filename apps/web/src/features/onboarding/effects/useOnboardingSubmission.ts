"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { useUserStore } from "@/stores/userStore";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { isResponsesComplete } from "../state/derive";
import type { OnboardingState } from "../state/types";

// Idempotency needs both the in-flight ref AND the persisted `completed`
// flag: remounts create a fresh ref while `state.server` is still null. The
// phase guard checks `phase !== "initial"` (not `server != null`) so the
// no-Gmail path, which resolves a snapshot before submit, isn't trapped.
export function useOnboardingSubmission(
  state: OnboardingState,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);
  const alreadyCompleted = useUserStore(
    (s) => s.onboarding?.completed === true,
  );

  useEffect(() => {
    if (inFlightRef.current) {
      console.debug("[onboarding:submit] skip — inFlight");
      return;
    }
    if (state.isRestarting) {
      console.debug("[onboarding:submit] skip — isRestarting");
      return;
    }
    const serverPhase = state.server?.phase;
    if (serverPhase && serverPhase !== "initial") {
      console.debug("[onboarding:submit] skip — phase", serverPhase);
      return;
    }
    if (alreadyCompleted) {
      console.debug("[onboarding:submit] skip — alreadyCompleted");
      return;
    }
    if (!isResponsesComplete(state)) {
      console.debug("[onboarding:submit] skip — responses incomplete", {
        questionIndex: state.questionIndex,
        gmail: state.responses?.gmail,
        focus: state.responses?.focus,
        clarifySubmitted: state.clarifySubmitted,
      });
      return;
    }
    console.debug("[onboarding:submit] FIRING POST /onboarding");

    inFlightRef.current = true;
    const responses = state.responses;
    const clarifyAnswers = state.clarifyQuestions
      ? state.clarifyQuestions.map((q) => {
          const a = state.clarifyAnswers[q.id];
          return {
            id: q.id,
            kind: q.kind,
            question: q.question,
            value:
              a?.kind === "option" || a?.kind === "custom" ? a.value : null,
          };
        })
      : undefined;
    const body = {
      name: responses[FIELD_NAMES.NAME]?.trim() ?? "",
      profession: responses[FIELD_NAMES.PROFESSION] ?? "",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      focus: responses[FIELD_NAMES.FOCUS] ?? "",
      ...(clarifyAnswers ? { clarify_answers: clarifyAnswers } : {}),
    };

    completeOnboarding(body)
      .then((response) => {
        if (response?.success && response.user) {
          onSuccess?.(response.user);
        }
      })
      .catch(() => {})
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, onSuccess, alreadyCompleted]);
}
