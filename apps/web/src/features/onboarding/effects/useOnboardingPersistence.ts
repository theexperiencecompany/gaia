"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { initialState } from "../state/initial";
import { loadPersisted, savePersisted } from "../state/persist";
import type { Action, OnboardingState } from "../state/types";

/**
 * Rehydrates once the signed-in user is known (the store hydrates from
 * localStorage after first paint, so `userId` is briefly empty) and saves every
 * change after that under that user's key.
 */
export function useOnboardingPersistence(
  userId: string,
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): void {
  const hydratedRef = useRef(false);

  useEffect(() => {
    if (hydratedRef.current || !userId) return;
    hydratedRef.current = true;
    const partial = loadPersisted(userId);
    if (partial) {
      dispatch({ type: "hydrate", partial });
    }
  }, [userId, dispatch]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    if (state === initialState) return;
    savePersisted(userId, state);
  }, [userId, state]);
}
