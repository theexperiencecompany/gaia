/**
 * GAIA's side of a turn, paced: lines land one at a time behind the wave
 * spinner (see `useTypedLines`). The spinner sits in the bubble lane, beside
 * where the next bubble will land, so it reads as GAIA working on the next
 * line rather than as a page loading.
 */

"use client";

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import * as m from "motion/react-m";

import { WaveSpinnerSquare } from "@/components/shared/WaveSpinnerSquare";

import { EASE_OUT_QUART } from "../constants/motion";
import { useTypedLines } from "../hooks/useTypedLines";
import { OnboardingBotBubble } from "./OnboardingBotBubble";

interface OnboardingPacedBubblesProps {
  lines: string[];
  /** Stable id for this turn; a turn already revealed this session is instant. */
  revealKey: string;
}

export function OnboardingPacedBubbles({
  lines,
  revealKey,
}: OnboardingPacedBubblesProps) {
  const { visibleLines, isTyping } = useTypedLines(lines, revealKey);
  return (
    <div className="flex flex-col gap-3">
      {visibleLines.length > 0 && (
        <OnboardingBotBubble
          text={visibleLines.join(NEW_MESSAGE_BREAK_TOKEN)}
        />
      )}
      {isTyping && (
        <m.output
          aria-label="GAIA is typing"
          className="ml-10.75 flex w-fit py-1"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: EASE_OUT_QUART }}
        >
          <WaveSpinnerSquare />
        </m.output>
      )}
    </div>
  );
}
