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
 */
export function useOnboardingPersistence(
  userId: string,
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const hydratedForRef = useRef<string | null>(null);
  // Set when a reset/hydrate has been dispatched but not yet rendered: the
  // save effect below still sees the previous user's state in that render.
  const awaitingHydratedStateRef = useRef(false);

  useEffect(() => {
    if (!userId || hydratedForRef.current === userId) return;
    const partial = loadPersisted(userId);
    if (hydratedForRef.current !== null) {
      dispatch({ type: "reset" });
      awaitingHydratedStateRef.current = true;
    }
    if (partial) {
      dispatch({ type: "hydrate", partial });
      awaitingHydratedStateRef.current = true;
    }
    hydratedForRef.current = userId;
  }, [userId, dispatch]);

  useEffect(() => {
    if (hydratedForRef.current !== userId) return;
    if (awaitingHydratedStateRef.current) {
      awaitingHydratedStateRef.current = false;
      return;
    }
    if (state === initialState) return;
    savePersisted(userId, state);
  }, [userId, state]);
}
