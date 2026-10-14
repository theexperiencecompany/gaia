/**
 * One choreography per GAIA turn: the typing dots show for a beat, then every
 * line of the turn lands in a single staggered motion, the way a burst of
 * texts arrives. Instant under reduced motion, in tests, and for a turn this
 * session already revealed (see `paceStore`).
 */

"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import type { PartChoreography } from "@/features/chat/utils/messageBreakUtils";

import { selectPaceDone, usePaceStore } from "../state/paceStore";

/** How long the dots show before the lines start landing. */
const TYPING_LEAD_MS = 420;
/** How the lines of a turn land: the gap between them and how long each takes. */
export const LINE_CHOREOGRAPHY: PartChoreography = {
  staggerSeconds: 0.26,
  durationSeconds: 0.34,
};
/** Breathing room after the last line before the reply appears. */
const SETTLE_MS = 120;

const INSTANT = process.env.NODE_ENV === "test";

/** Reveals are skipped outright under reduced motion and in tests. */
function useIsPaceInstant(): boolean {
  const reducedMotion = useReducedMotion();
  return INSTANT || !!reducedMotion;
}

/** Whether GAIA has finished "typing" the turn with this key — true at once
 * wherever pacing is off, so replies never wait on a reveal that won't run. */
export function usePaceDone(revealKey: string): boolean {
  const instant = useIsPaceInstant();
  const done = usePaceStore(selectPaceDone(revealKey));
  return instant || done;
}

type TypingPhase = "typing" | "landing" | "done";

export function useTypedLines(
  lineCount: number,
  revealKey: string,
  /** History, not the live turn: never pace it, just record it as seen. */
  forceInstant = false,
): TypingPhase {
  const alreadyDone = usePaceStore(selectPaceDone(revealKey));
  const markDone = usePaceStore((s) => s.markDone);
  const instant = useIsPaceInstant() || alreadyDone || forceInstant;
  const [phase, setPhase] = useState<TypingPhase>(instant ? "done" : "typing");

  useEffect(() => {
    if (instant) {
      if (!alreadyDone) markDone(revealKey);
      return;
    }
    if (phase === "typing") {
      const timer = setTimeout(() => setPhase("landing"), TYPING_LEAD_MS);
      return () => clearTimeout(timer);
    }
    if (phase === "landing") {
      const lastLineLandsMs =
        ((lineCount - 1) * LINE_CHOREOGRAPHY.staggerSeconds +
          LINE_CHOREOGRAPHY.durationSeconds) *
        1000;
      const timer = setTimeout(() => {
        setPhase("done");
        markDone(revealKey);
      }, lastLineLandsMs + SETTLE_MS);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [phase, instant, alreadyDone, markDone, revealKey, lineCount]);

  return instant ? "done" : phase;
}
