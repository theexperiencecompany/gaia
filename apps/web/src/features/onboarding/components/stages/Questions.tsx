/**
 * `questions` stage. Active until every required question has been
 * answered. The transcript renders in `MessagesRegion`; this file only
 * owns the active question's composer (text / Autocomplete / Gmail).
 */

"use client";

import type { Dispatch } from "react";
import { useCallback, useEffect, useRef } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { FIELD_NAMES, questions } from "../../constants";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingInput } from "../OnboardingInput";

interface QuestionsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function QuestionsComposer({ state, dispatch }: QuestionsProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const user = useUser();
  const currentQuestion = questions[state.questionIndex];
  const prefilledRef = useRef(false);

  // Pre-fill the name draft from the account name at most once per mount,
  // retrying until the persisted user store has actually hydrated.
  useEffect(() => {
    if (prefilledRef.current) return;
    if (
      currentQuestion?.fieldName === FIELD_NAMES.NAME &&
      !state.responses[FIELD_NAMES.NAME] &&
      !state.draftText &&
      user.name
    ) {
      prefilledRef.current = true;
      dispatch({ type: "draftText", value: user.name });
    }
  }, [currentQuestion, state.responses, state.draftText, user.name, dispatch]);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!currentQuestion) return;

      const field = currentQuestion.fieldName;
      const value =
        field === FIELD_NAMES.PROFESSION
          ? state.draftProfession?.trim() || null
          : state.draftText.trim() || null;

      if (!value) return;
      dispatch({ type: "answer", field, value });
    },
    [currentQuestion, state.draftProfession, state.draftText, dispatch],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      dispatch({ type: "draftText", value });
    },
    [dispatch],
  );

  const handleProfessionInputChange = useCallback(
    (value: string) => {
      dispatch({ type: "draftProfession", value: value || null });
    },
    [dispatch],
  );

  const handleProfessionSelect = useCallback(
    (key: React.Key | null) => {
      const value = key != null ? String(key) : null;
      dispatch({ type: "draftProfession", value });
      if (value) {
        dispatch({ type: "answer", field: FIELD_NAMES.PROFESSION, value });
      }
    },
    [dispatch],
  );

  const handleGmailSkip = useCallback(() => {
    dispatch({ type: "answer", field: FIELD_NAMES.GMAIL, value: "skipped" });
  }, [dispatch]);

  return (
    <OnboardingInput
      mode="qa"
      questionIndex={state.questionIndex}
      draftText={state.draftText}
      draftProfession={state.draftProfession}
      inputRef={inputRef}
      onSubmit={handleSubmit}
      onInputChange={handleInputChange}
      onProfessionSelect={handleProfessionSelect}
      onProfessionInputChange={handleProfessionInputChange}
      onGmailSkip={handleGmailSkip}
    />
  );
}
