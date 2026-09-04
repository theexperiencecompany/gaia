"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { getBrowserTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
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
 *
 * A failure is said out loud: the stage shows "Starting your first conversation…"
 * with nothing else on screen, so a swallowed error is a wizard that hangs.
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
  const otherNeed = state.otherNeed.trim();

  useEffect(() => {
    if (stage !== "chat") return;
    if (inFlightRef.current) return;
    if (state.isRestarting) return;
    if (alreadyCompleted) return;

    inFlightRef.current = true;
    completeOnboarding({
      profession: state.responses[FIELD_NAMES.PROFESSION] ?? "",
      needs: state.selectedNeeds,
      ...(otherNeed ? { other_need: otherNeed } : {}),
      timezone: getBrowserTimezone(),
    })
      .then((response) => {
        if (response?.success && response.user) onSuccess?.(response.user);
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
