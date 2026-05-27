"use client";

import { useEffect, useRef } from "react";

import { postPhase } from "../api/onboardingApi";
import type { Stage } from "../state/types";

export function usePhaseSync(stage: Stage): void {
  const postedRef = useRef(false);

  useEffect(() => {
    if (postedRef.current) return;
    if (stage !== "chat") return;

    postedRef.current = true;
    postPhase("getting_started").catch(() => {});
  }, [stage]);
}
