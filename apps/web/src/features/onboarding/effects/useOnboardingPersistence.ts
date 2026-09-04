"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { initialState } from "../state/initial";
import { loadPersisted, savePersisted } from "../state/persist";
import type { Action, OnboardingState } from "../state/types";

/**
 * Keeps the wizard in step with the signed-in user's cache. The user store
 * rehydrates from localStorage before the session is confirmed, so the id can
 * change after first paint: each new id starts from its own cache (or from
 * scratch), and nothing is written under an id the state was not loaded for.
 *
 * Returns whether the current user's cache has been applied. Anything that
 * reads the restored state (the funnel's `onboarding:started`) has to wait for
 * this, because the hydrate dispatch lands a render later than the mount.
 * Which user is loaded lives in the reducer (`state.hydratedFor`), so this
 * hook holds no state of its own.
 */
export function useOnboardingPersistence(
  userId: string,
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): boolean {
  const { hydratedFor } = state;
  // Set when a reset/hydrate has been dispatched but not yet rendered: the
  // save effect below still sees the previous user's state in that render.
  const awaitingHydratedStateRef = useRef(false);

  useEffect(() => {
    if (!userId || hydratedFor === userId) return;
    const partial = loadPersisted(userId);
    if (hydratedFor !== null) dispatch({ type: "reset" });
    if (partial) dispatch({ type: "hydrate", partial });
    dispatch({ type: "hydrated", userId });
    awaitingHydratedStateRef.current = true;
  }, [userId, hydratedFor, dispatch]);

  useEffect(() => {
    if (hydratedFor !== userId) return;
    if (awaitingHydratedStateRef.current) {
      awaitingHydratedStateRef.current = false;
      return;
    }
    if (state === initialState) return;
    savePersisted(userId, state);
  }, [userId, hydratedFor, state]);

  return hydratedFor === userId && userId !== "";
}
