/** What became of one native emoji reaction; only ATTACHED means it landed. */

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
 * Fired when GAIA reacts to the user's message; `replaces` is the emoji it put there
 * earlier in the turn, which this one replaces. Resolves ATTACHED once the emoji is
 * attached natively to that message.
 */
export type ReactionHandler = (
  emoji: string,
  replaces: string | null,
) => Promise<ReactionOutcome>;
