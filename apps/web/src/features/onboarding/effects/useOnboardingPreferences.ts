"use client";

import type { OnboardingAnswers } from "@shared/api/generated";
import { type MutationStatus, useMutation } from "@tanstack/react-query";
import { type Dispatch, useCallback, useEffect, useMemo, useRef } from "react";

import { shouldRetryQuery } from "@/lib/queryClient";

import { saveOnboardingAnswers } from "../api/onboardingApi";
import { FIELD_NAMES, questions } from "../constants";
import type { Action, OnboardingState } from "../state/types";

export interface AnswersSave {
  status: MutationStatus;
  retry: () => void;
}

/**
 * Persists Q1 (profession) and Q2 (needs) the moment Q2 is confirmed: the
 * platform-link opener and the first chat are composed from the stored answers.
 * The wizard holds on the questions stage until this lands; a network or 5xx
 * failure retries with backoff, and one that still fails waits on "Try again".
 */
export function useOnboardingPreferences(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): AnswersSave {
  const questionsComplete = state.questionIndex >= questions.length;
  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const { selectedNeeds, preferencesPersisted, isRestarting } = state;
  const otherNeed = state.otherNeed.trim();

  const answers = useMemo<OnboardingAnswers | null>(() => {
    if (!profession || (selectedNeeds.length === 0 && !otherNeed)) return null;
    return {
      profession,
      needs: selectedNeeds,
      ...(otherNeed ? { other_need: otherNeed } : {}),
    };
  }, [profession, selectedNeeds, otherNeed]);

  const { mutate, status, reset } = useMutation({
    mutationFn: (answers: OnboardingAnswers) => saveOnboardingAnswers(answers),
    retry: shouldRetryQuery,
    onSuccess: () => dispatch({ type: "preferencesPersisted" }),
    onError: (error: unknown) => {
      console.error("[onboarding] saving your answers failed:", error);
    },
  });

  const pending = questionsComplete && !preferencesPersisted && !isRestarting;
  const save = useCallback(() => {
    if (pending && answers) mutate(answers);
  }, [pending, answers, mutate]);

  // A ref, not the mutation status: StrictMode re-runs the effect before the
  // first mutate has re-rendered as pending, and the answers must go out once.
  const autoSavedRef = useRef(false);
  useEffect(() => {
    if (isRestarting) {
      autoSavedRef.current = false;
      reset();
      return;
    }
    if (!pending || !answers || autoSavedRef.current) return;
    autoSavedRef.current = true;
    save();
  }, [isRestarting, pending, answers, save, reset]);

  return { status: preferencesPersisted ? "success" : status, retry: save };
}
