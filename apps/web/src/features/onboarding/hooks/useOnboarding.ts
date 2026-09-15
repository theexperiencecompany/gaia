/**
 * Top-level orchestrator hook for the onboarding flow. Wires the reducer to
 * every effect (persistence, submission, analytics) and exposes the derived
 * stage plus a `restart` action that wipes local state and asks the server
 * to reset.
 *
 * The stage cursor needs one fact this reducer does not own — whether the
 * user is subscribed — so it is read here and passed into `getStage`.
 */

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useReducer } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import {
  patchCurrentUser,
  setCurrentUser,
  useCurrentUser,
  useCurrentUserIsFresh,
} from "@/features/auth/hooks/useCurrentUser";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

import { resetOnboarding } from "../api/onboardingApi";
import { useOnboardingAnalytics } from "../effects/useOnboardingAnalytics";
import { useOnboardingPersistence } from "../effects/useOnboardingPersistence";
import { useOnboardingPreferences } from "../effects/useOnboardingPreferences";
import { useOnboardingSubmission } from "../effects/useOnboardingSubmission";
import { draftFromServerPreferences, getStage } from "../state/derive";
import { initialState } from "../state/initial";
import { usePaceStore } from "../state/paceStore";
import {
  clearIntroSeen,
  clearPersisted,
  saveIntroSeen,
} from "../state/persist";
import { reducer } from "../state/reducer";
import type { Action, OnboardingState, Stage } from "../state/types";

interface UseOnboardingReturn {
  state: OnboardingState;
  stage: Stage;
  dispatch: React.Dispatch<Action>;
  /** Whether the intro has already been watched; `null` until storage is read. */
  introSeen: boolean | null;
  markIntroSeen: () => void;
  restart: () => Promise<void>;
}

export function useOnboarding(): UseOnboardingReturn {
  const queryClient = useQueryClient();
  const { userId, onboarding } = useCurrentUser();
  // The persisted user cache paints first and may predate a server-side
  // reset; the draft is only reconciled against an answer from this session.
  const userIsFresh = useCurrentUserIsFresh();
  const [state, dispatch] = useReducer(reducer, initialState);
  const { isPaid } = useIsPaid();
  const stage = getStage(state, isPaid);

  // Stable per user record: the hydrate effect takes it as a dependency.
  const serverDraft = useMemo(
    () => draftFromServerPreferences(onboarding),
    [onboarding],
  );

  const hydrated = useOnboardingPersistence(
    userIsFresh ? userId : "",
    serverDraft,
    state,
    dispatch,
  );
  useOnboardingPreferences(state, dispatch);

  const handleSubmissionSuccess = useCallback(
    (info: UserInfo) => {
      setCurrentUser(queryClient, info);
    },
    [queryClient],
  );
  useOnboardingSubmission(state, stage, handleSubmissionSuccess);

  useOnboardingAnalytics(state, stage, hydrated);

  const markIntroSeen = useCallback(() => {
    saveIntroSeen(userId);
    dispatch({ type: "introSeen" });
  }, [userId]);

  // Every part of a restart lives here: the caches (wizard blob, intro flag,
  // typed-line pacing), the reducer, the user record and the server reset.
  const restart = useCallback(async () => {
    if (state.isRestarting) return;

    // Captured before the reset, so the event says where the user gave up.
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_RESTARTED, { from_stage: stage });
    clearPersisted(userId);
    clearIntroSeen(userId);
    usePaceStore.getState().reset();
    dispatch({ type: "restartStart" });
    patchCurrentUser(queryClient, { onboarding: undefined });

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
  }, [state.isRestarting, stage, userId, queryClient]);

  return {
    state,
    stage,
    dispatch,
    introSeen: state.introSeen,
    markIntroSeen,
    restart,
  };
}
