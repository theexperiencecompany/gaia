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
    // Submitted users already past clarify shouldn't refetch — protects
    // against the edge case where persisted state has `clarifySubmitted=true`
    // but `clarifyQuestions=null` (e.g. corrupted session, schema migration).
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
      .catch(() => {
        // Silent — the user can still progress if the request fails; the
        // composer guards on `clarifyQuestions != null` and the backend
        // gives a fallback set, so retrying once is enough.
      })
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
