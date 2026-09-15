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
 * Keeps the wizard in step with the signed-in user's cache: the user store can
 * rehydrate a new id after first paint, so each id starts from its own cache.
 * Returns whether that cache has been applied — callers of the restored state
 * (`onboarding:started`) must wait, since hydrate lands a render after mount.
 * The server outranks the cache both ways: a draft claiming completion with no
 * server prefs (a reset) is dropped; a missing draft falls back to the account's answers instead of re-asking.
 */
export function useOnboardingPersistence(
  userId: string,
  serverDraft: Partial<OnboardingState> | null,
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
    if (partial?.preferencesPersisted && !serverDraft) {
      clearPersisted(userId);
      partial = null;
    }
    // This device's own progress outranks the server's copy of the answers:
    // it is the more recent of the two, and it holds the later stages.
    partial = partial ?? serverDraft;
    if (hydratedFor !== null) dispatch({ type: "reset" });
    // The intro flag resolves on the same beat, cache or no cache: until it
    // does it is `null`, and the page renders neither the intro nor the flow.
    dispatch({
      type: "hydrate",
      partial: { ...(partial ?? {}), introSeen: loadIntroSeen(userId) },
    });
    dispatch({ type: "hydrated", userId });
    awaitingHydratedStateRef.current = true;
  }, [userId, serverDraft, hydratedFor, dispatch]);

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
