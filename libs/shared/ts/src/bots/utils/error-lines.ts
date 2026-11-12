/** The lines a bot shows when GAIA could not answer, shared by every failure path. */

import type { Entry } from "../../conversation/types";

export const BOT_ERROR_LINE = {
  GENERIC: "❌ Something went wrong. Please try again later.",
  CONNECTION_INTERRUPTED: "🔌 Connection interrupted. Please try again.",
} as const;

type ReplyFailure = NonNullable<
  Extract<Entry, { kind: "reply_settled" }>["failure"]
>;

/** What a failed reply tells the user, by why it failed: the lines the bots showed before the step. */
export const REPLY_FAILURE_LINE: Record<ReplyFailure, string> = {
  model_error: BOT_ERROR_LINE.GENERIC,
  step_limit: BOT_ERROR_LINE.GENERIC,
  server_restart: BOT_ERROR_LINE.CONNECTION_INTERRUPTED,
};
