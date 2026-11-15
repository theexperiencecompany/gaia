/** The lines a bot shows when GAIA could not answer, shared by every failure path. */

export const BOT_ERROR_LINE = {
  GENERIC: "❌ Something went wrong. Please try again later.",
  CONNECTION_INTERRUPTED: "🔌 Connection interrupted. Please try again.",
} as const;
