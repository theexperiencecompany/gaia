/**
 * Utility functions for handling NEW_MESSAGE_BREAK tokens in chat messages
 * Enables WhatsApp-style multiple bubble responses from a single message
 */

/**
 * The literal sentinel the LLM emits to signal "split into a new bubble here".
 * Single source of truth — every consumer (bot streaming, frontend rendering,
 * message persistence) should reference this constant rather than duplicating
 * the string. Length is exposed separately as a small convenience for
 * substring math.
 */
export const NEW_MESSAGE_BREAK_TOKEN = "<NEW_MESSAGE_BREAK>";
export const NEW_MESSAGE_BREAK_TOKEN_LENGTH = NEW_MESSAGE_BREAK_TOKEN.length;

export function splitMessageByBreaks(content: string): string[] {
  // Return empty array for empty/whitespace content
  if (!content?.trim()) {
    return [];
  }

  if (!content.includes(NEW_MESSAGE_BREAK_TOKEN)) {
    return [content];
  }

  return content
    .split(NEW_MESSAGE_BREAK_TOKEN)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}
