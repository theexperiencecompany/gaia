/**
 * `focus` stage. Active when the user skipped Gmail; collects the focus
 * answer that replaces inbox-derived signal in the no-Gmail pipeline. No
 * content panel — uses the shared transcript above the composer.
 */

"use client";

import type { Dispatch } from "react";
import { useCallback, useRef } from "react";
import { FIELD_NAMES } from "../../constants";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingInput } from "../OnboardingInput";

interface FocusProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function FocusComposer({ state, dispatch }: FocusProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const value = state.draftText.trim();
      if (!value) return;
      dispatch({ type: "answer", field: FIELD_NAMES.FOCUS, value });
    },
    [state.draftText, dispatch],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      dispatch({ type: "draftText", value });
    },
    [dispatch],
  );

  return (
    <OnboardingInput
      mode="focus"
      draftText={state.draftText}
      inputRef={inputRef}
      onSubmit={handleSubmit}
      onInputChange={handleInputChange}
    />
  );
}
