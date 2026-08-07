"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { getBrowserTimezone } from "@/lib/timezone";
import { useUserStore } from "@/stores/userStore";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { hasGmail, isResponsesComplete } from "../state/derive";
import type { OnboardingState } from "../state/types";

// Idempotency needs both the in-flight ref AND the persisted `completed`
// flag: remounts create a fresh ref while `state.server` is still null. The
// phase guard checks `phase !== "initial"` (not `server != null`) so the
// no-Gmail path, which resolves a snapshot before submit, isn't trapped.
//
// Gmail path fires the moment responses are complete (right after the Gmail
// connect) with `defer_workflows: true` so the backend starts inbox
// intelligence immediately; workflows wait for POST /onboarding/integrations
// (see useIntegrationsSubmission). The no-Gmail path still waits for
// integration selection and runs the full pipeline in one job.
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
    const gmailConnected = hasGmail(state);
    if (!gmailConnected && !state.integrationSelectDone) {
      console.debug("[onboarding:submit] skip — integration selection pending");
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
      timezone: getBrowserTimezone(),
      focus: responses[FIELD_NAMES.FOCUS] ?? "",
      working_on: responses[FIELD_NAMES.WORKING_ON] ?? "",
      ...(clarifyAnswers ? { clarify_answers: clarifyAnswers } : {}),
      ...(state.selectedIntegrations.length > 0
        ? { selected_integrations: state.selectedIntegrations }
        : {}),
      ...(gmailConnected ? { defer_workflows: true } : {}),
    };

    completeOnboarding(body)
      .then((response) => {
        if (response?.success && response.user) {
          onSuccess?.(response.user);
        }
      })
      .catch((error) => {
        console.error("[onboarding:submit] completion request failed:", error);
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, onSuccess, alreadyCompleted]);
}
