"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { toast } from "@/lib/toast";

import { saveOnboardingPreferences } from "../api/onboardingApi";
import { FIELD_NAMES, questions } from "../constants";
import type { Action, OnboardingState } from "../state/types";

/**
 * Persists Q1 (profession) and Q2 (needs) the moment Q2 is confirmed, several
 * stages before the flow's final `POST /onboarding` — the platform-link
 * opener is composed from these *stored* answers, so writing early is what
 * stops it degrading to a generic "Hi! Who are you?" on handoff.
 *
 * A failure is surfaced, not swallowed: `preferencesPersisted` stays false.
 */
export function useOnboardingPreferences(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const inFlightRef = useRef(false);

  const questionsComplete = state.questionIndex >= questions.length;
  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const { selectedNeeds, preferencesPersisted, isRestarting } = state;
  const otherNeed = state.otherNeed.trim();

  useEffect(() => {
    if (!questionsComplete) return;
    if (preferencesPersisted) return;
    if (isRestarting) return;
    if (inFlightRef.current) return;
    if (!profession || (selectedNeeds.length === 0 && !otherNeed)) return;

    inFlightRef.current = true;
    saveOnboardingPreferences({
      profession,
      needs: selectedNeeds,
      ...(otherNeed ? { other_need: otherNeed } : {}),
    })
      .then(() => dispatch({ type: "preferencesPersisted" }))
      .catch((error: unknown) => {
        inFlightRef.current = false;
        console.error("[onboarding] saving your answers failed:", error);
        toast.error(
          "We couldn't save your answers. Reload the page and try again.",
        );
      });
  }, [
    questionsComplete,
    preferencesPersisted,
    isRestarting,
    profession,
    selectedNeeds,
    otherNeed,
    dispatch,
  ]);
}
