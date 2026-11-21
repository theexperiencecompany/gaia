import type { MessageReaction } from "@shared/api/generated";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import {
  REACTION_BADGE_HEIGHT_PX,
  REACTION_EMOJI_PX,
  REACTION_FILL_CLASS,
  REACTION_OVERHANG_SIDE_PX,
  REACTION_OVERHANG_TOP_PX,
  REACTION_RING_PX,
  REACTION_TAIL,
} from "@/features/chat/constants/reactionBadge";
import { cn } from "@/lib/utils";

interface MessageReactionsProps {
  reaction: MessageReaction;
}

const POP_EASE = [0.34, 1.56, 0.64, 1] as const;
const PAGE_BG_RING = `0 0 0 ${REACTION_RING_PX}px var(--color-primary-bg)`;

/**
 * iMessage tapback GAIA leaves on a user's bubble: a badge on the bubble's top
 * left corner with a tail pointing at it. Render inside a `relative` bubble.
 * A replaced reaction swaps its glyph in place; the badge pops in only once.
 */
export function MessageReactions({ reaction }: MessageReactionsProps) {
  const reduceMotion = useReducedMotion();

  return (
    <m.div
      aria-label="Reaction"
      role="group"
      initial={reduceMotion ? false : { scale: 0.4, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.3, ease: POP_EASE }}
      className="absolute z-10 select-none"
      style={{
        top: -REACTION_OVERHANG_TOP_PX,
        left: -REACTION_OVERHANG_SIDE_PX,
        transformOrigin: "right bottom",
      }}
    >
      <div
        className={cn(
          "flex items-center justify-center rounded-full leading-none",
          REACTION_FILL_CLASS,
        )}
        style={{
          height: REACTION_BADGE_HEIGHT_PX,
          minWidth: REACTION_BADGE_HEIGHT_PX,
          boxShadow: PAGE_BG_RING,
          fontSize: REACTION_EMOJI_PX,
        }}
      >
        {reaction.emoji}
      </div>
      {REACTION_TAIL.map(({ size, edge, top }) => (
        <span
          key={top}
          aria-hidden
          className={cn("absolute rounded-full", REACTION_FILL_CLASS)}
          style={{ width: size, height: size, top, right: edge }}
        />
      ))}
    </m.div>
  );
}
