"use client";

import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

/** Long enough to read a step, short enough that the whole run stays under five seconds. */
const STEP_MS = 1100;

/** Ticks through a demo run one step at a time; reduced motion lands on the finished run. */
export function useDemoRun(stepCount: number) {
  const reduceMotion = useReducedMotion();
  const [doneCount, setDoneCount] = useState(0);
  const [runId, setRunId] = useState(0);

  useEffect(() => {
    if (reduceMotion) {
      setDoneCount(stepCount);
      return;
    }
    setDoneCount(0);
    const timer = setInterval(() => {
      setDoneCount((count) => {
        if (count + 1 >= stepCount) clearInterval(timer);
        return Math.min(count + 1, stepCount);
      });
    }, STEP_MS);
    return () => clearInterval(timer);
  }, [stepCount, reduceMotion, runId]);

  const replay = useCallback(() => setRunId((id) => id + 1), []);

  return {
    doneCount,
    isDone: doneCount >= stepCount,
    elapsedSeconds: Math.round((doneCount * STEP_MS) / 1000),
    replay,
  };
}
