"use client";

import { useEffect, useRef } from "react";

import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import type { OnboardingState, Stage } from "../state/types";

/**
 * Onboarding funnel events. Only `onboarding:started` is client-owned — step
 * and completion analytics live server-side (POST /onboarding/phase emits
 * onboarding:step_completed; the worker emits onboarding:completed), so
 * emitting them here too would double-count.
 */
export function useOnboardingAnalytics(
  state: OnboardingState,
  _stage: Stage,
  hydrated: boolean,
): void {
  const startedRef = useRef(false);

  useEffect(() => {
    // Waits for persisted state to restore: any earlier and every resumed
    // session reports has_saved_state:false, before the hydrate dispatch renders.
    if (!hydrated || startedRef.current) return;
    startedRef.current = true;
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, {
      has_saved_state: state.questionIndex > 0,
    });
  }, [hydrated, state.questionIndex]);
}
