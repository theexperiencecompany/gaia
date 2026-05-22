/**
 * Fetches the LLM-generated clarify questions once the user enters the
 * clarify stage. The backend always returns 3 (falling back to a hardcoded
 * set if the LLM call fails), so we don't need a separate loading/empty
 * surface on the frontend — the composer renders the seeded questions the
 * moment they arrive.
 *
 * The fetch is gated on (name, profession, focus) being non-empty. Once
 * the questions land they're committed to the reducer via `clarifyLoaded`
 * which also persists them across reloads.
 */

"use client";

import { type Dispatch, useEffect, useRef } from "react";
import { getClarifyQuestions } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import type { Action, OnboardingState } from "../state/types";

export function useClarifyQuestions(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (state.clarifyQuestions != null) return;
    if (inFlightRef.current) return;
    if (state.clarifySubmitted) return;

    const name = state.responses[FIELD_NAMES.NAME]?.trim();
    const profession = state.responses[FIELD_NAMES.PROFESSION]?.trim();
    const focus = state.responses[FIELD_NAMES.FOCUS]?.trim();
    if (!name || !profession || !focus) return;
    if (state.responses[FIELD_NAMES.GMAIL] !== "skipped") return;

    inFlightRef.current = true;
    getClarifyQuestions({ name, profession, focus })
      .then((res) => {
        if (!res?.questions?.length) return;
        dispatch({ type: "clarifyLoaded", questions: res.questions });
      })
      .catch(() => {})
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [
    state.clarifyQuestions,
    state.clarifySubmitted,
    state.responses,
    dispatch,
  ]);
}
