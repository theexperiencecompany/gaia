"use client";

import { useEffect, useRef } from "react";

import { useUserStore } from "@/stores/userStore";

import { submitOnboardingIntegrations } from "../api/onboardingApi";
import { hasGmail } from "../state/derive";
import type { OnboardingState } from "../state/types";

// Gmail-path phase 2: once the user confirms their integration picks, POST
// them so the backend enqueues the deferred workflows job. Gated on the early
// submission being accepted (userStore onboarding.completed or a non-initial
// server phase) — the endpoint 409s before the onboarding subdoc exists.
// The endpoint is idempotent, so a reload-triggered replay is harmless.
export function useIntegrationsSubmission(state: OnboardingState): void {
  const inFlightRef = useRef(false);
  const submittedRef = useRef(false);
  const onboardingAccepted = useUserStore(
    (s) => s.onboarding?.completed === true,
  );

  useEffect(() => {
    if (state.isRestarting) {
      submittedRef.current = false;
    }
  }, [state.isRestarting]);

  useEffect(() => {
    if (inFlightRef.current || submittedRef.current) return;
    if (state.isRestarting) return;
    if (!hasGmail(state)) return;
    if (!state.integrationSelectDone) return;
    const serverPhase = state.server?.phase;
    const accepted =
      onboardingAccepted || (serverPhase != null && serverPhase !== "initial");
    if (!accepted) return;

    inFlightRef.current = true;
    submitOnboardingIntegrations(state.selectedIntegrations)
      .then(() => {
        submittedRef.current = true;
      })
      .catch((err) => {
        // Leave submittedRef false so a later state change retries; the endpoint
        // is idempotent. Log it so a persistent failure (e.g. 503) is visible
        // instead of silently leaving the user stuck in PERSONALIZATION_PENDING.
        console.error(
          "[onboarding:integrations] submit failed, will retry",
          err,
        );
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, onboardingAccepted]);
}
