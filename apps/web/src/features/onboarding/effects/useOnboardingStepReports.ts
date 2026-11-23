"use client";

import type { OnboardingPhaseUpdateRequest } from "@shared/api/generated";
import { useEffect, useMemo, useRef } from "react";

import { reportOnboardingStep } from "../api/onboardingApi";
import type { Stage } from "../state/types";

type ReportedOnboardingStep = OnboardingPhaseUpdateRequest["phase"];

/**
 * The browser-only steps the wizard has reached on this stage. The paywall
 * counts only once the plan status is known: while it loads, a paying user
 * is parked on the payment stage too.
 */
function stepsReachedOn(
  stage: Stage,
  planStatusKnown: boolean,
): ReportedOnboardingStep[] {
  if (stage === "payment")
    return planStatusKnown ? ["started", "paywall_reached"] : ["started"];
  if (stage === "paidReveal") return ["started", "paid_reveal_seen"];
  return ["started"];
}

/**
 * Reports each wizard step to the server, which stamps it once per onboarding
 * run and owns its analytics event — so a reload re-reporting a step is a
 * no-op there, and nothing here tracks the event itself. questions_answered
 * needs no report: the answers save stamps it.
 */
export function useOnboardingStepReports(
  stage: Stage,
  hydrated: boolean,
  planStatusKnown: boolean,
  isRestarting: boolean,
): void {
  const reportedRef = useRef(new Set<ReportedOnboardingStep>());
  const steps = useMemo(
    () => (hydrated ? stepsReachedOn(stage, planStatusKnown) : []),
    [hydrated, stage, planStatusKnown],
  );

  useEffect(() => {
    // A restart wipes the server's stamps, so the new run reports afresh.
    if (isRestarting) {
      reportedRef.current.clear();
      return;
    }
    for (const step of steps) {
      if (reportedRef.current.has(step)) continue;
      reportedRef.current.add(step);
      reportOnboardingStep(step).catch((error: unknown) => {
        reportedRef.current.delete(step);
        console.error(`[onboarding] reporting ${step} failed:`, error);
      });
    }
  }, [steps, isRestarting]);
}
