/**
 * What became of one native emoji reaction, and the analytics it reports.
 *
 * Shared by the live-turn hook and the outbound consumer so both report the
 * same `bot:reaction_delivered` shape; only ATTACHED means the reaction landed.
 */

import type { EventProperties } from "../../analytics";

export const REACTION_OUTCOME = {
  /** The platform accepted the reaction. */
  ATTACHED: "attached",
  /** The platform has no reaction API (the BaseBotAdapter default). */
  PLATFORM_UNSUPPORTED: "platform_unsupported",
  /** The platform names reactions and has no name for this emoji (Slack shortcodes). */
  UNMAPPED_EMOJI: "unmapped_emoji",
  /** The platform call threw (off-list emoji, API error, unreachable message). */
  ATTACH_FAILED: "attach_failed",
  /** The turn has no inbound user message to react to. */
  NO_TARGET: "no_target",
} as const;

export type ReactionOutcome =
  (typeof REACTION_OUTCOME)[keyof typeof REACTION_OUTCOME];

/**
 * Fired when the turn resolved to a one-emoji acknowledgment of the user's message.
 *
 * Resolves ATTACHED once the emoji is attached natively to that message, which
 * then IS the reply; any other outcome sends the emoji as the turn's text instead.
 */
export type ReactionHandler = (emoji: string) => Promise<ReactionOutcome>;

/** Which path delivered the reaction: a reply to a live turn, or an outbound envelope. */
export const REACTION_SURFACE = {
  LIVE: "live",
  OUTBOUND: "outbound",
} as const;

type ReactionSurface = (typeof REACTION_SURFACE)[keyof typeof REACTION_SURFACE];

const REACTION_DELIVERY = {
  NATIVE: "native",
  FALLBACK_TEXT: "fallback_text",
} as const;

/** The `bot:reaction_delivered` properties for one reaction attempt. */
export function reactionDeliveredProperties(
  outcome: ReactionOutcome,
  surface: ReactionSurface,
): EventProperties["bot:reaction_delivered"] {
  if (outcome === REACTION_OUTCOME.ATTACHED) {
    return { success: true, surface, delivery: REACTION_DELIVERY.NATIVE };
  }
  return {
    success: true,
    surface,
    delivery: REACTION_DELIVERY.FALLBACK_TEXT,
    reason: outcome,
  };
}
