"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { getBrowserTimezone } from "@/lib/timezone";
import { useUserStore } from "@/stores/userStore";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import type { OnboardingState, Stage } from "../state/types";

/**
 * Submits the onboarding answers exactly once, when the flow reaches its
 * final stage. Submitting here (rather than as soon as the questions are
 * answered) is what keeps the user inside the flow: the server marks
 * onboarding complete, and completion is precisely what the onboarding
 * guard uses to route them out into `/c`.
 *
 * Idempotency needs both the in-flight ref AND the persisted `completed`
 * flag — a remount creates a fresh ref.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  stage: Stage,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);
  const alreadyCompleted = useUserStore(
    (s) => s.onboarding?.completed === true,
  );

  useEffect(() => {
    if (stage !== "chat") return;
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
    if (alreadyCompleted) return;

    inFlightRef.current = true;
    completeOnboarding({
      profession: state.responses[FIELD_NAMES.PROFESSION] ?? "",
      needs: state.selectedNeeds,
      timezone: getBrowserTimezone(),
    })
      .then((response) => {
        if (response?.success && response.user) onSuccess?.(response.user);
      })
      .catch((error) => {
        console.error("[onboarding:submit] completion request failed:", error);
        inFlightRef.current = false;
      });
  }, [
    stage,
    state.isRestarting,
    state.responses,
    state.selectedNeeds,
    alreadyCompleted,
    onSuccess,
  ]);
}
