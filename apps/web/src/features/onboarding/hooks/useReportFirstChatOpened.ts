"use client";

import { useEffect, useRef } from "react";

import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

import { reportOnboardingStep } from "../api/onboardingApi";

/**
 * Reports first_chat_opened when the open conversation is the one onboarding
 * seeded. The server stamps it once per onboarding run, so reopening that
 * conversation later is a no-op there.
 */
export function useReportFirstChatOpened(conversationId: string | null): void {
  const seededId = useCurrentUser().onboarding?.getting_started_conversation_id;
  const reportedRef = useRef(false);

  useEffect(() => {
    if (!conversationId || conversationId !== seededId || reportedRef.current)
      return;
    reportedRef.current = true;
    reportOnboardingStep("first_chat_opened").catch((error: unknown) => {
      reportedRef.current = false;
      console.error("[onboarding] reporting first_chat_opened failed:", error);
    });
  }, [conversationId, seededId]);
}
