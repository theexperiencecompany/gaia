"use client";

import { useEffect, useRef } from "react";

import { authApi } from "@/features/auth/api/authApi";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { getBrowserTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";

import { FIELD_NAMES } from "../constants";
import type { OnboardingState, Stage } from "../state/types";

/**
 * Submits the onboarding answers exactly once, at the flow's final stage —
 * submitting only here (not as questions are answered) keeps the user inside
 * the flow, since the onboarding guard routes on server completion.
 *
 * Idempotency needs both the in-flight ref AND the persisted `completed` flag,
 * since a remount creates a fresh ref. Failures surface — a swallowed error would hang the wizard on "One sec…" silently.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  stage: Stage,
  onSuccess?: () => void,
): void {
  const inFlightRef = useRef(false);
  const alreadyCompleted = useCurrentUser().onboarding?.completed === true;
  const otherNeed = state.otherNeed.trim();

  useEffect(() => {
    if (stage !== "chat") return;
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
    if (alreadyCompleted) return;

    inFlightRef.current = true;
    authApi
      .completeOnboarding({
        profession: state.responses[FIELD_NAMES.PROFESSION] ?? "",
        needs: state.selectedNeeds,
        ...(otherNeed ? { other_need: otherNeed } : {}),
        timezone: getBrowserTimezone(),
      })
      .then((response) => {
        if (response?.success) onSuccess?.();
      })
      .catch((error: unknown) => {
        inFlightRef.current = false;
        console.error("[onboarding:submit] completion request failed:", error);
        toast.error(
          "We couldn't finish setting up your chat. Reload the page to try again.",
        );
      });
  }, [
    stage,
    state.isRestarting,
    state.responses,
    state.selectedNeeds,
    otherNeed,
    alreadyCompleted,
    onSuccess,
  ]);
}
