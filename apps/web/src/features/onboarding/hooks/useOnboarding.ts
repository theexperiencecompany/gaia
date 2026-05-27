/**
 * Top-level orchestrator hook for the onboarding flow. Wires the reducer to
 * every effect (persistence, OAuth, Gmail auto-advance, submission, backend
 * sync, phase, analytics, auto-redirect) and exposes the derived stage plus
 * a `restart` action that wipes local state and asks the server to reset.
 */

"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useReducer, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { userInfoToStoreUser } from "@/features/auth/utils/userInfoToStoreUser";
import { db as chatDb } from "@/lib/db/chatDb";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/stores/chatStore";

import { resetOnboarding } from "../api/onboardingApi";
import { questions } from "../constants";
import { useBackendSync } from "../effects/useBackendSync";
import { useGmailAutoAdvance } from "../effects/useGmailAutoAdvance";
import { useOAuthCallback } from "../effects/useOAuthCallback";
import { useOnboardingAnalytics } from "../effects/useOnboardingAnalytics";
import { useOnboardingPersistence } from "../effects/useOnboardingPersistence";
import { useOnboardingSubmission } from "../effects/useOnboardingSubmission";
import { usePhaseSync } from "../effects/usePhaseSync";
import { getStage } from "../state/derive";
import { initialState } from "../state/initial";
import { clearPersisted } from "../state/persist";
import { reducer } from "../state/reducer";
import type { Action, OnboardingState, Stage } from "../state/types";
import { useClarifyQuestions } from "./useClarifyQuestions";

interface UseOnboardingReturn {
  state: OnboardingState;
  stage: Stage;
  dispatch: React.Dispatch<Action>;
  restart: () => Promise<void>;
}

interface UseOnboardingArgs {
  skipAutoRedirect?: boolean;
}

export function useOnboarding({
  skipAutoRedirect = false,
}: UseOnboardingArgs = {}): UseOnboardingReturn {
  const router = useRouter();
  const user = useUser();
  const { setUser, updateUser } = useUserActions();
  const [state, dispatch] = useReducer(reducer, initialState);
  const stage = getStage(state);

  useOnboardingPersistence(state, dispatch);

  // Resume past the Q&A if the backend already accepted a submission, so a
  // post-clear reload doesn't drop the user back on Q1.
  useEffect(() => {
    if (state.questionIndex >= questions.length) return;
    if (state.isRestarting) return;
    const onboarding = user.onboarding;
    if (!onboarding?.completed) return;
    if (onboarding.phase === "completed") return;
    dispatch({
      type: "hydrate",
      partial: { questionIndex: questions.length },
    });
  }, [user.onboarding, state.questionIndex, state.isRestarting]);

  useGmailAutoAdvance(state, dispatch);

  useOAuthCallback(dispatch);

  const handleSubmissionSuccess = useCallback(
    (info: UserInfo) => {
      setUser(userInfoToStoreUser(info));
    },
    [setUser],
  );
  useOnboardingSubmission(state, handleSubmissionSuccess);

  useClarifyQuestions(state, dispatch);

  useBackendSync(state, stage, dispatch);

  usePhaseSync(stage);

  useOnboardingAnalytics(state);

  const redirectedRef = useRef(false);
  useEffect(() => {
    if (skipAutoRedirect) return;
    if (redirectedRef.current) return;
    if (stage !== "chat") return;
    const conversationId = state.server?.first_message_conversation_id;
    if (!conversationId) return;
    redirectedRef.current = true;
    router.push(`/c/${conversationId}`);
  }, [
    stage,
    state.server?.first_message_conversation_id,
    skipAutoRedirect,
    router,
  ]);

  const restart = useCallback(async () => {
    if (state.isRestarting) return;

    const oldConversationId = state.server?.first_message_conversation_id;

    clearPersisted();
    dispatch({ type: "restartStart" });
    updateUser({ onboarding: undefined });

    if (oldConversationId) {
      useChatStore.getState().removeConversation(oldConversationId);
      void chatDb
        .deleteConversationAndMessages(oldConversationId)
        .catch((error: unknown) => {
          console.error(
            "Failed to delete onboarding conversation from IndexedDB:",
            error,
          );
        });
    }

    redirectedRef.current = false;

    try {
      await resetOnboarding();
    } catch (error) {
      console.error("Failed to reset onboarding on server:", error);
      toast.error(
        "We reset locally, but the server reset didn't fully complete.",
      );
    } finally {
      dispatch({ type: "restartDone" });
    }
  }, [
    state.isRestarting,
    state.server?.first_message_conversation_id,
    updateUser,
  ]);

  return { state, stage, dispatch, restart };
}
