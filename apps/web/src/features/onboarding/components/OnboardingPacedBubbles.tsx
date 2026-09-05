/**
 * GAIA's side of a turn, paced: the dots bubble shows for a beat, then the
 * whole turn lands as one staggered motion while the dots fade out in place,
 * so the first line reads as the dots becoming words (see `useTypedLines`).
 */

"use client";

import { Spinner } from "@heroui/spinner";
import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";

import { EASE_OUT_QUART } from "../constants/motion";
import { LINE_CHOREOGRAPHY, useTypedLines } from "../hooks/useTypedLines";
import { OnboardingBotBubble } from "./OnboardingBotBubble";

interface OnboardingPacedBubblesProps {
  lines: string[];
  /** Stable id for this turn; a turn already revealed this session is instant. */
  revealKey: string;
  /** An answered turn from the transcript: render at once, never pace. */
  instant?: boolean;
}

export function OnboardingPacedBubbles({
  lines,
  revealKey,
  instant = false,
}: OnboardingPacedBubblesProps) {
  const phase = useTypedLines(lines.length, revealKey, instant);
  const showLines = phase !== "typing";
  return (
    <div className="relative">
      <AnimatePresence>
        {phase === "typing" && (
          // Same bubble a text part renders in (iMessage chrome, tail, avatar
          // lane), holding the dots instead of words. Absolutely placed so the
          // first line lands exactly where the dots were, not underneath them.
          <div
            key="typing"
            className="chatbubblebot_parent absolute inset-x-0 top-0 pl-10.75"
          >
            <m.output
              aria-label="GAIA is typing"
              className="imessage-bubble imessage-from-them imessage-grouped-last flex w-fit items-center"
              initial={{ opacity: 0, y: 6, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.94, transition: { duration: 0.18 } }}
              transition={{ duration: 0.22, ease: EASE_OUT_QUART }}
            >
              {/* Wrapper pinned to the text line-height so the bubble is exactly
                  as tall as a one-line reply; dots a step lighter than
                  HeroUI's default so they read on the bubble's zinc-800. */}
              <Spinner
                variant="dots"
                color="default"
                size="md"
                classNames={{ wrapper: "h-6", dots: "bg-zinc-400" }}
              />
            </m.output>
          </div>
        )}
      </AnimatePresence>
      {showLines ? (
        <OnboardingBotBubble
          text={lines.join(NEW_MESSAGE_BREAK_TOKEN)}
          partChoreography={phase === "done" ? undefined : LINE_CHOREOGRAPHY}
        />
      ) : (
        // Holds the lane's height while the dots are absolute, so nothing
        // below jumps when the lines take over.
        <div className="h-10" aria-hidden />
      )}
    </div>
  );
}
