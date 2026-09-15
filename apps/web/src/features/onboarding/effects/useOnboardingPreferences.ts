"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { toast } from "@/lib/toast";

import { saveOnboardingPreferences } from "../api/onboardingApi";
import { FIELD_NAMES, questions } from "../constants";
import type { Action, OnboardingState } from "../state/types";

/**
 * Persists Q1 (profession) and Q2 (needs) the moment Q2 is confirmed —
 * several stages before the flow's final `POST /onboarding`.
 *
 * The server composes the platform-link opener ("Hi! I'm a founder. I could
 * use help with my inbox and my todos. Who are you?") from the *stored*
 * answers, and the platform stage mints that code long before the completion
 * call runs. Writing the answers here is what stops the opener — on the web
 * and on every platform handoff — from degrading to "Hi! Who are you?".
 *
 * A failure is surfaced, not swallowed: `preferencesPersisted` stays false, so
 * nothing mints a code composed from answers the server never received.
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
