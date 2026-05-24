"use client";

import { type Dispatch, useEffect } from "react";

import { useFetchIntegrationStatus } from "@/features/integrations/hooks/useIntegrations";

import { FIELD_NAMES, questions } from "../constants";
import type { Action, OnboardingState } from "../state/types";

interface IntegrationStatusEntry {
  integrationId: string;
  connected: boolean;
}

export function useGmailAutoAdvance(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const { data: integrationStatus } = useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  useEffect(() => {
    const gmailQuestionIndex = questions.findIndex(
      (q) => q.fieldName === FIELD_NAMES.GMAIL,
    );
    if (state.questionIndex !== gmailQuestionIndex) return;
    if (state.responses[FIELD_NAMES.GMAIL] != null) return;

    const integrations =
      (integrationStatus?.integrations as
        | IntegrationStatusEntry[]
        | undefined) ?? [];
    const gmail = integrations.find((i) => i.integrationId === "gmail");
    if (gmail?.connected) {
      dispatch({
        type: "answer",
        field: FIELD_NAMES.GMAIL,
        value: "connected",
      });
    }
  }, [integrationStatus, state.questionIndex, state.responses, dispatch]);
}
