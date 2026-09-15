"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { initialState } from "../state/initial";
import {
  clearPersisted,
  loadIntroSeen,
  loadPersisted,
  savePersisted,
} from "../state/persist";
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
 *
 * The server outranks the cache. A draft that claims the preferences were
 * persisted while the account has none is a leftover from before a reset
 * (the dev reset script, an admin unset); rehydrating it would skip every
 * stage and re-complete onboarding on the first paint. It is dropped.
 */
export function useOnboardingPersistence(
  userId: string,
  serverHasPreferences: boolean,
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): boolean {
  const { hydratedFor } = state;
  // Set when a reset/hydrate has been dispatched but not yet rendered: the
  // save effect below still sees the previous user's state in that render.
  const awaitingHydratedStateRef = useRef(false);

  useEffect(() => {
    if (!userId || hydratedFor === userId) return;
    let partial = loadPersisted(userId);
    if (partial?.preferencesPersisted && !serverHasPreferences) {
      clearPersisted(userId);
      partial = null;
    }
    if (hydratedFor !== null) dispatch({ type: "reset" });
    // The intro flag resolves on the same beat, cache or no cache: until it
    // does it is `null`, and the page renders neither the intro nor the flow.
    dispatch({
      type: "hydrate",
      partial: { ...(partial ?? {}), introSeen: loadIntroSeen(userId) },
    });
    dispatch({ type: "hydrated", userId });
    awaitingHydratedStateRef.current = true;
  }, [userId, serverHasPreferences, hydratedFor, dispatch]);

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
