"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { isResponsesComplete } from "../state/derive";
import type { OnboardingState } from "../state/types";

/**
 * Fires POST /onboarding once all required answers are captured and the
 * pipeline hasn't started yet. Idempotent via an in-flight ref.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
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
      .catch(() => {
        // Submission failed; processing stage stays as-is.
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, onSuccess]);
}
