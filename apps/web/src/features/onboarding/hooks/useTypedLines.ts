/**
 * Reveals GAIA's lines one at a time with a "typing" pause before each, so a
 * turn reads like a person sending a few texts rather than a wall appearing
 * at once. The pause scales with the line so a long one feels typed and a
 * short one snaps. Instant under reduced motion, in tests, and for a turn
 * this session already revealed (see `paceStore`).
 */

"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { selectPaceDone, usePaceStore } from "../state/paceStore";

const BASE_PAUSE_MS = 180;
const PER_CHAR_MS = 3;
const MAX_PAUSE_MS = 550;
/** Breathing room between the last line landing and the reply appearing. */
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

function typingPauseFor(line: string): number {
  return Math.min(MAX_PAUSE_MS, BASE_PAUSE_MS + line.length * PER_CHAR_MS);
}

export interface TypedLines {
  visibleLines: string[];
  isTyping: boolean;
  /** True once every line is on screen and the settle pause has passed. */
  done: boolean;
}

export function useTypedLines(lines: string[], revealKey: string): TypedLines {
  const alreadyDone = usePaceStore(selectPaceDone(revealKey));
  const markDone = usePaceStore((s) => s.markDone);
  const instant = useIsPaceInstant() || alreadyDone;
  const [count, setCount] = useState(instant ? lines.length : 0);
  // Identity of `lines` changes every render (callers build it on the fly);
  // key the schedule on the content so a parent re-render never resets it.
  const script = lines.join("\n");

  useEffect(() => {
    if (instant) {
      if (!alreadyDone) markDone(revealKey);
      return;
    }
    const total = script.split("\n").length;
    if (count >= total) {
      const timer = setTimeout(() => markDone(revealKey), SETTLE_MS);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(
      () => setCount((c) => c + 1),
      typingPauseFor(script.split("\n")[count] ?? ""),
    );
    return () => clearTimeout(timer);
  }, [count, instant, alreadyDone, markDone, revealKey, script]);

  const shown = instant ? lines.length : count;
  return {
    visibleLines: lines.slice(0, shown),
    isTyping: !instant && shown < lines.length,
    done: instant || alreadyDone,
  };
}
