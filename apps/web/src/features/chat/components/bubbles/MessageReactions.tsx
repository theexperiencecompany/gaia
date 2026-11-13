import { groupReactions } from "@shared/utils";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import type { MessageReaction } from "@/config/registries/baseMessageRegistry";
import {
  CAPSULE_TAIL,
  REACTION_BADGE_HEIGHT_PX,
  REACTION_COUNT_CLASS,
  REACTION_EMOJI_PX,
  REACTION_FILL_CLASS,
  REACTION_OVERHANG_SIDE_PX,
  REACTION_OVERHANG_TOP_PX,
  REACTION_RING_PX,
  SINGLE_TAIL,
} from "@/features/chat/constants/reactionBadge";
import { cn } from "@/lib/utils";

interface MessageReactionsProps {
  reactions: MessageReaction[];
}

const POP_EASE = [0.34, 1.56, 0.64, 1] as const;
const PAGE_BG_RING = `0 0 0 ${REACTION_RING_PX}px var(--color-primary-bg)`;

/**
 * iMessage tapback GAIA leaves on a user's bubble: a badge on the bubble's top
 * left corner with a tail pointing at it. Render inside a `relative` bubble.
 */
export function MessageReactions({ reactions }: MessageReactionsProps) {
  const reduceMotion = useReducedMotion();
  if (reactions.length === 0) return null;

  const grouped = groupReactions(reactions);
  const isSingle = grouped.length === 1 && grouped[0].count === 1;
  const tail = isSingle ? SINGLE_TAIL : CAPSULE_TAIL;

  return (
    <m.div
      aria-label="Reactions"
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
          "flex items-center justify-center gap-1 rounded-full leading-none",
          REACTION_FILL_CLASS,
        )}
        style={{
          height: REACTION_BADGE_HEIGHT_PX,
          minWidth: REACTION_BADGE_HEIGHT_PX,
          paddingInline: isSingle ? 0 : REACTION_BADGE_HEIGHT_PX * 0.3,
          boxShadow: PAGE_BG_RING,
          fontSize: REACTION_EMOJI_PX,
        }}
      >
        {grouped.map(({ emoji, count }) => (
          <span key={emoji} className="flex items-center gap-0.5">
            <span>{emoji}</span>
            {count > 1 && (
              <span
                className={cn("font-medium text-[10px]", REACTION_COUNT_CLASS)}
              >
                {count}
              </span>
            )}
          </span>
        ))}
      </div>
      {tail.map(({ size, edge, top }) => (
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
