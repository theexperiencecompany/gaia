"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { initialState } from "../state/initial";
import { loadPersisted, savePersisted } from "../state/persist";
import type { Action, OnboardingState } from "../state/types";

/**
 * Hydrates the reducer from sessionStorage on first mount, then writes the
 * whitelisted slice on every state change. The hydration guard ensures we
 * never overwrite persisted state with `initialState` during the first
 * render before hydration runs.
 */
export function useOnboardingPersistence(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const hydratedRef = useRef(false);

  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    const partial = loadPersisted();
    if (partial) {
      dispatch({ type: "hydrate", partial });
    }
  }, [dispatch]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    if (state === initialState) return;
    savePersisted(state);
  }, [state]);
}
