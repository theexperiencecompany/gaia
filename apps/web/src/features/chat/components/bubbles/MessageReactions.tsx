import { groupReactions } from "@shared/utils";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import type { CSSProperties } from "react";
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
      className="absolute top-(--reaction-top) left-(--reaction-left) z-10 origin-bottom-right select-none"
      style={
        {
          "--reaction-top": `${-REACTION_OVERHANG_TOP_PX}px`,
          "--reaction-left": `${-REACTION_OVERHANG_SIDE_PX}px`,
          "--reaction-badge": `${REACTION_BADGE_HEIGHT_PX}px`,
          "--reaction-pad": `${isSingle ? 0 : REACTION_BADGE_HEIGHT_PX * 0.3}px`,
          "--reaction-ring": PAGE_BG_RING,
          "--reaction-emoji": `${REACTION_EMOJI_PX}px`,
        } as CSSProperties
      }
    >
      <div
        className={cn(
          "flex h-(--reaction-badge) min-w-(--reaction-badge) items-center justify-center gap-1 rounded-full px-(--reaction-pad) text-(length:--reaction-emoji) leading-none shadow-(--reaction-ring)",
          REACTION_FILL_CLASS,
        )}
      >
        {grouped.map(({ emoji, count }) => (
          <span key={emoji} className="flex items-center gap-0.5">
            <span>{emoji}</span>
            {count > 1 && (
              <span className={cn("font-medium text-xs", REACTION_COUNT_CLASS)}>
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
          className={cn(
            "absolute top-(--dot-top) right-(--dot-edge) size-(--dot-size) rounded-full",
            REACTION_FILL_CLASS,
          )}
          style={
            {
              "--dot-size": `${size}px`,
              "--dot-top": `${top}px`,
              "--dot-edge": `${edge}px`,
            } as CSSProperties
          }
        />
      ))}
    </m.div>
  );
}
