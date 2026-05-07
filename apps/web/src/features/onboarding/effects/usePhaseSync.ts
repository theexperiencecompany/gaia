"use client";

import { useEffect, useRef } from "react";

import { postPhase } from "../api/onboardingApi";
import type { Stage } from "../state/types";

/**
 * Posts `/onboarding/phase` with `getting_started` exactly once, the first
 * time the derived stage transitions to `chat`. Failures are swallowed —
 * phase tracking is bookkeeping, never blocks the user.
 */
export function usePhaseSync(stage: Stage): void {
  const postedRef = useRef(false);

  useEffect(() => {
    if (postedRef.current) return;
    if (stage !== "chat") return;

    postedRef.current = true;
    postPhase("getting_started").catch(() => {
      // non-blocking — phase tracking is bookkeeping
    });
  }, [stage]);
}
