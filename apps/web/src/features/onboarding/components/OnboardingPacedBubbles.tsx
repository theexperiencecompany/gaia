/**
 * GAIA's side of a turn, paced: lines land one at a time behind a typing
 * indicator (see `useTypedLines`). The indicator sits in the bubble lane so
 * it reads as the next bubble forming, not as a spinner.
 */

"use client";

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import * as m from "motion/react-m";

import { EASE_OUT_QUART } from "../constants/motion";
import { useTypedLines } from "../hooks/useTypedLines";
import { OnboardingBotBubble } from "./OnboardingBotBubble";

const DOT_DELAYS_SECONDS = [0, 0.15, 0.3];

export function OnboardingTypingBubble() {
  return (
    <m.output
      aria-label="GAIA is typing"
      className="ml-10.75 flex w-fit items-center gap-1.5 rounded-[25px] rounded-bl-none bg-zinc-800 px-4 py-3.5"
      initial={{ opacity: 0, y: 6, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.25, ease: EASE_OUT_QUART }}
    >
      {DOT_DELAYS_SECONDS.map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-bounce rounded-full bg-zinc-400"
          style={{ animationDelay: `${delay}s` }}
        />
      ))}
    </m.output>
  );
}

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
    <div className="flex flex-col gap-2">
      {visibleLines.length > 0 && (
        <OnboardingBotBubble
          text={visibleLines.join(NEW_MESSAGE_BREAK_TOKEN)}
        />
      )}
      {isTyping && <OnboardingTypingBubble />}
    </div>
  );
}
