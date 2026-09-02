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

import { useCallback, useReducer } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { userInfoToStoreUser } from "@/features/auth/utils/userInfoToStoreUser";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { toast } from "@/lib/toast";
import { useUserStore } from "@/stores/userStore";

import { resetOnboarding } from "../api/onboardingApi";
import { useOnboardingAnalytics } from "../effects/useOnboardingAnalytics";
import { useOnboardingPersistence } from "../effects/useOnboardingPersistence";
import { useOnboardingPreferences } from "../effects/useOnboardingPreferences";
import { useOnboardingSubmission } from "../effects/useOnboardingSubmission";
import { getStage } from "../state/derive";
import { initialState } from "../state/initial";
import { clearPersisted } from "../state/persist";
import { reducer } from "../state/reducer";
import type { Action, OnboardingState, Stage } from "../state/types";

interface UseOnboardingReturn {
  state: OnboardingState;
  stage: Stage;
  dispatch: React.Dispatch<Action>;
  restart: () => Promise<void>;
}

export function useOnboarding(): UseOnboardingReturn {
  const { setUser, updateUser } = useUserActions();
  const userId = useUserStore((s) => s.userId);
  const [state, dispatch] = useReducer(reducer, initialState);
  const { isPaid } = useIsPaid();
  const stage = getStage(state, isPaid);

  useOnboardingPersistence(userId, state, dispatch);
  useOnboardingPreferences(state, dispatch);

  const handleSubmissionSuccess = useCallback(
    (info: UserInfo) => {
      setUser(userInfoToStoreUser(info));
    },
    [setUser],
  );
  useOnboardingSubmission(state, stage, handleSubmissionSuccess);

  useOnboardingAnalytics(state, stage);

  const restart = useCallback(async () => {
    if (state.isRestarting) return;

    clearPersisted(userId);
    dispatch({ type: "restartStart" });
    updateUser({ onboarding: undefined });

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
  }, [state.isRestarting, userId, updateUser]);

  return { state, stage, dispatch, restart };
}
