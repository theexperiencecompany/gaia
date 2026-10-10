"use client";

import type { OnboardingRequest } from "@shared/api/generated";
import { type MutationStatus, useMutation } from "@tanstack/react-query";
import { useCallback } from "react";

import { authApi } from "@/features/auth/api/authApi";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { getBrowserTimezone } from "@/lib/timezone";

import { FIELD_NAMES } from "../constants";
import type { OnboardingState } from "../state/types";

export interface OnboardingSubmission {
  submit: () => void;
  status: MutationStatus;
}

/**
 * Submits the onboarding answers, only ever from a user's click: confirming the
 * platform step, or asking again after a failure. A failure stays failed until
 * then — an effect that re-submitted on re-render once sent 31k requests on a 422.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  onSuccess: () => void,
): OnboardingSubmission {
  const alreadyCompleted = useCurrentUser().onboarding?.completed === true;
  const { mutate, status } = useMutation({
    mutationFn: (request: OnboardingRequest) =>
      authApi.completeOnboarding(request),
    retry: false,
    onSuccess: (response) => {
      if (response?.success) onSuccess();
    },
    onError: (error: unknown) => {
      console.error("[onboarding:submit] completion request failed:", error);
    },
  });

  const profession = state.responses[FIELD_NAMES.PROFESSION] ?? "";
  const otherNeed = state.otherNeed.trim();
  const submit = useCallback(() => {
    if (alreadyCompleted || state.isRestarting || status === "pending") return;
    mutate({
      profession,
      needs: state.selectedNeeds,
      ...(otherNeed ? { other_need: otherNeed } : {}),
      timezone: getBrowserTimezone(),
    });
  }, [
    alreadyCompleted,
    state.isRestarting,
    state.selectedNeeds,
    status,
    mutate,
    profession,
    otherNeed,
  ]);

  return { submit, status };
}
