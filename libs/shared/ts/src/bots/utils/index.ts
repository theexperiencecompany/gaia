/**
 * Bot utility barrel export.
 *
 * Three layers of reusable logic, ordered from low-level to high-level:
 *
 * 1. formatters - Pure functions that turn data into display strings.
 *    Use these when you need custom response assembly.
 *
 * 2. commands  - Business-logic handlers that call GaiaClient, format results,
 *    and return a ready-to-send string. Bot adapters call these directly.
 *
 * 3. streaming - handleStreamingChat: full streaming lifecycle handler.
 *    Bot adapters provide three callbacks (editMessage, onAuthError, onGenericError)
 *    and the shared function handles throttling, cursor display, and error routing.
 *
 * Platform character limits and truncation are also exported here.
 */

export * from "./commands";
export * from "./formatters";
export * from "./streaming";

/**
 * Parses whitespace-separated text into a subcommand and remaining args.
 * Used by Slack and Telegram command handlers where input is plain text.
 *
 * @param text - Raw command text.
 * @param skipFirst - If true, skips the first token (e.g. for Telegram where the command name is included).
 * @returns The parsed subcommand (defaults to "list") and remaining args.
 */
export function parseTextArgs(
  text: string,
  skipFirst = false,
): { subcommand: string; args: string[] } {
  const parts = text.trim().split(/\s+/);
  const tokens = skipFirst ? parts.slice(1) : parts;
  return { subcommand: tokens[0] || "list", args: tokens.slice(1) };
}

/** Per-platform message character limits. Used by truncateResponse. */
export const PLATFORM_LIMITS: Record<string, number> = {
  discord: 2000,
  slack: 4000,
  telegram: 4096,
  whatsapp: 4096,
};

/**
 * Truncates a response message to fit within the platform's character limit.
 * Truncates at word boundaries and optionally appends a web app link.
 *
 * @param text - The message text to truncate.
 * @param platform - The target platform (discord, slack, telegram, whatsapp).
 * @param conversationUrl - Optional URL to the full conversation on the web app.
 * @returns The truncated message.
 */
export function truncateResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
  conversationUrl?: string,
): string {
  const limit = PLATFORM_LIMITS[platform];
  if (text.length <= limit) {
    return text;
  }

  const suffix = conversationUrl
    ? `\n\n[View full response](${conversationUrl})`
    : "\n\n... (truncated)";
  const maxLen = limit - suffix.length;

  // Truncate at word boundary, avoiding cuts inside markdown links
  let truncated = text.slice(0, maxLen);
  const lastSpace = truncated.lastIndexOf(" ");
  if (lastSpace > maxLen * 0.8) {
    truncated = truncated.slice(0, lastSpace);
  }

  // If we cut inside a markdown link [label](url), backtrack to before the link
  const lastOpenBracket = truncated.lastIndexOf("[");
  if (lastOpenBracket > -1) {
    const closeParen = text.indexOf(")", lastOpenBracket);
    if (closeParen > -1 && closeParen > truncated.length) {
      // We're inside an incomplete link — backtrack to before it
      const beforeLink = truncated.lastIndexOf("\n", lastOpenBracket);
      if (beforeLink > maxLen * 0.5) {
        truncated = truncated.slice(0, beforeLink);
      }
    }
  }

  return truncated + suffix;
}
