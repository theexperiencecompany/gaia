"use client";

import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

export type RunStage = "connect" | "working" | "done" | "skipped";

const TICK_MS = 50;

/** Connect, then a visible run of runMs, then the result; reduced motion skips the run, skip() skips the connect. */
export function useStagedRun(runMs: number) {
  const reduceMotion = useReducedMotion();
  const [stage, setStage] = useState<RunStage>("connect");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (stage !== "working") return;
    if (reduceMotion) {
      setProgress(1);
      setStage("done");
      return;
    }
    const startedAt = Date.now();
    const timer = setInterval(() => {
      const next = Math.min((Date.now() - startedAt) / runMs, 1);
      setProgress(next);
      if (next >= 1) {
        clearInterval(timer);
        setStage("done");
      }
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [stage, runMs, reduceMotion]);

  const start = useCallback(() => {
    setProgress(0);
    setStage("working");
  }, []);

  const skip = useCallback(() => setStage("skipped"), []);

  return { stage, progress, start, skip };
}
