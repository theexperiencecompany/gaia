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
export * from "./logger";
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

/**
 * Splits a long response into platform-sized chunks for delivery as multiple
 * messages instead of a single truncated bubble. Used by non-streaming bot
 * adapters (WhatsApp, Discord) so the user receives the full content.
 *
 * Splits prefer paragraph (`\n\n`) boundaries, then sentence enders
 * (`. `, `! `, `? `, `\n`), then the last word boundary, then a hard cut as a
 * last resort. Each returned chunk is guaranteed to be ≤ the platform limit.
 *
 * @param text - The full message text.
 * @param platform - The target platform (discord, slack, telegram, whatsapp).
 * @returns An array of chunks, in order, each ≤ the platform character limit.
 *   Returns ``[text]`` when ``text`` already fits.
 */
export function chunkResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
): string[] {
  const limit = PLATFORM_LIMITS[platform];
  if (text.length <= limit) return [text];

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > limit) {
    let cutAt = -1;
    const window = remaining.slice(0, limit);

    // Prefer paragraph break
    cutAt = window.lastIndexOf("\n\n");
    if (cutAt < limit * 0.5) cutAt = -1;

    // Fall back to sentence end
    if (cutAt === -1) {
      const candidates = [". ", "! ", "? ", "\n"];
      for (const sep of candidates) {
        const idx = window.lastIndexOf(sep);
        if (idx > limit * 0.5 && idx > cutAt) cutAt = idx + sep.length;
      }
    }

    // Fall back to last word boundary
    if (cutAt === -1) {
      const space = window.lastIndexOf(" ");
      if (space > limit * 0.5) cutAt = space + 1;
    }

    // Hard cut as last resort
    if (cutAt === -1) cutAt = limit;

    chunks.push(remaining.slice(0, cutAt).trimEnd());
    remaining = remaining.slice(cutAt).trimStart();
  }

  if (remaining.length > 0) chunks.push(remaining);
  return chunks.filter((c) => c.length > 0);
}
