"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { useUserStore } from "@/stores/userStore";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { isResponsesComplete } from "../state/derive";
import type { OnboardingState } from "../state/types";

/**
 * Fires POST /onboarding once all required answers are captured and the
 * pipeline hasn't started yet. Idempotent via an in-flight ref *and* the
 * persisted `user.onboarding.completed` flag — the in-flight ref alone is
 * insufficient because any remount (OAuth bounce, back-nav from /c/{id},
 * manual refresh) creates a fresh ref while `state.server` is still null
 * until `useBackendSync`'s async snapshot fetch resolves. Without the
 * persisted guard, the user-store flag wins that race and a duplicate POST
 * fires, re-running the intelligence pipeline.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);
  const alreadyCompleted = useUserStore(
    (s) => s.onboarding?.completed === true,
  );

  useEffect(() => {
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
    if (state.server != null) return;
    if (alreadyCompleted) return;
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
  }, [state, onSuccess, alreadyCompleted]);
}
