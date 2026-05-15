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

/**
 * Returns `{ state, stage, dispatch, restart }`. If the authed user already
 * completed the onboarding submission server-side (per `user.onboarding`)
 * but hasn't reached chat yet, this hook resumes them past the Q&A so a
 * post-clear reload doesn't drop them back on Q1. Pass `skipAutoRedirect`
 * to keep them on this page when chat is reached (used by the page itself
 * which renders the chat stage inline).
 *
 * `restart` clears persisted state, dispatches `restartStart`, drops the
 * old conversation from chat store + IndexedDB, then calls the server
 * `/reset` endpoint. The reducer is locked via `isRestarting` until done.
 */
export function useOnboarding({
  skipAutoRedirect = false,
}: UseOnboardingArgs = {}): UseOnboardingReturn {
  const router = useRouter();
  const user = useUser();
  const { setUser, updateUser } = useUserActions();
  const [state, dispatch] = useReducer(reducer, initialState);
  const stage = getStage(state);

  // Persist + hydrate from localStorage
  useOnboardingPersistence(state, dispatch);

  // Resume mid-pipeline if backend says onboarding was already submitted but
  // hasn't reached chat. Without this, a user reloading after the
  // localStorage was cleared would land back on Q1. The `questionIndex`
  // guard naturally short-circuits subsequent runs once we've hydrated past
  // the Q&A — no ref needed.
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

  // Auto-advance Gmail if integration shows connected on reload
  useGmailAutoAdvance(state, dispatch);

  // Handle ?oauth_success / ?oauth_error from URL
  useOAuthCallback(dispatch);

  // Submit POST /onboarding when responses complete and pipeline hasn't started
  const handleSubmissionSuccess = useCallback(
    (info: UserInfo) => {
      setUser(userInfoToStoreUser(info));
    },
    [setUser],
  );
  useOnboardingSubmission(state, handleSubmissionSuccess);

  // No-Gmail clarify follow-up: fetch the 3 LLM-generated questions once
  // the user has answered the focus prompt. Gated internally on the no-Gmail
  // path, so this is a no-op for Gmail users.
  useClarifyQuestions(state, dispatch);

  // WS + initial snapshot fetch
  useBackendSync(state, stage, dispatch);

  // POST /onboarding/phase once when entering chat stage
  usePhaseSync(stage);

  // Analytics
  useOnboardingAnalytics(state);

  // Auto-redirect into the live chat once the conversation is ready
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

  // Restart: optimistic local reset + backend /reset in background
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
