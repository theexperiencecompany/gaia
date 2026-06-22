"use client";

import { type Dispatch, useEffect } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { FIELD_NAMES, questions } from "../constants";
import type { Action, OnboardingState } from "../state/types";

export function useGmailAutoAdvance(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const { getIntegrationStatus } = useIntegrations();

  useEffect(() => {
    const gmailQuestionIndex = questions.findIndex(
      (q) => q.fieldName === FIELD_NAMES.GMAIL,
    );
    if (state.questionIndex !== gmailQuestionIndex) return;
    if (state.responses[FIELD_NAMES.GMAIL] != null) return;

    if (getIntegrationStatus("gmail")?.connected) {
      dispatch({
        type: "answer",
        field: FIELD_NAMES.GMAIL,
        value: "connected",
      });
    }
  }, [getIntegrationStatus, state.questionIndex, state.responses, dispatch]);
}
