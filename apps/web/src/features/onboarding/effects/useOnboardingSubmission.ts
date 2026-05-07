"use client";

import { type Dispatch, useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { isResponsesComplete } from "../state/derive";
import type { Action, OnboardingState } from "../state/types";

/**
 * Fires POST /onboarding once all required answers are captured and the
 * pipeline hasn't started yet. Idempotent via an in-flight ref and a 409
 * short-circuit (server already accepted a prior submission). On failure it
 * sets `submissionError` so the processing composer can offer a retry.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);

  useEffect(() => {
    // Guard combo implies stage === "processing": responses complete + no
    // server snapshot yet + not restarting + no prior error.
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
    if (state.submissionError) return;
    if (state.server != null) return;
    if (!isResponsesComplete(state)) return;

    inFlightRef.current = true;
    const responses = state.responses;
    const body = {
      name: responses[FIELD_NAMES.NAME]?.trim() ?? "",
      profession: responses[FIELD_NAMES.PROFESSION] ?? "",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      focus: responses[FIELD_NAMES.FOCUS] ?? "",
    };

    completeOnboarding(body)
      .then((response) => {
        if (response?.success && response.user) {
          onSuccess?.(response.user);
        }
      })
      .catch((error: unknown) => {
        const err = error as { response?: { status?: number } };
        if (err?.response?.status === 409) {
          return;
        }
        dispatch({ type: "submitError" });
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, dispatch, onSuccess]);
}
