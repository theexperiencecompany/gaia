/**
 * GAIA's side of a turn, paced: lines land one at a time behind a bubble
 * holding the dots spinner (see `useTypedLines`), the way messaging apps show
 * the other person typing.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import * as m from "motion/react-m";

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
        // The same bubble a text part renders in (iMessage chrome, tail, avatar
        // lane), holding the dots instead of words.
        <div className="chatbubblebot_parent pl-10.75">
          <m.output
            aria-label="GAIA is typing"
            className="imessage-bubble imessage-from-them imessage-grouped-last flex w-fit items-center py-2.5"
            initial={{ opacity: 0, y: 4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.2, ease: EASE_OUT_QUART }}
          >
            <Spinner variant="dots" color="default" size="md" />
          </m.output>
        </div>
      )}
    </div>
  );
}
