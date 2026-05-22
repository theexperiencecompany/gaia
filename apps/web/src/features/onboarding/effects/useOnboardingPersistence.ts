"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { initialState } from "../state/initial";
import { loadPersisted, savePersisted } from "../state/persist";
import type { Action, OnboardingState } from "../state/types";

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
