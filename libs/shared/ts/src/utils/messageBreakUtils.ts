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

/**
 * Length of the longest suffix of `text` that is an incomplete prefix of the
 * break token — i.e. a token that has only half-arrived across stream chunks
 * (e.g. `"...now<NEW_MESSAGE_B"` → 14). Returns 0 when the tail cannot be the
 * start of a token. Never matches a complete token (capped at length-1).
 */
export function trailingPartialBreakLength(text: string): number {
  const max = Math.min(text.length, NEW_MESSAGE_BREAK_TOKEN_LENGTH - 1);
  for (let len = max; len > 0; len--) {
    if (NEW_MESSAGE_BREAK_TOKEN.startsWith(text.slice(-len))) return len;
  }
  return 0;
}

/**
 * The portion of a live streaming buffer that is safe to show in a bubble:
 * complete break tokens stripped, and any trailing half-arrived token withheld
 * so a partial `<NEW_MESSAGE_B` never leaks into the display. The withheld tail
 * is shown once the next chunk completes the token (routed to a new bubble) or
 * rules it out.
 */
export function displaySafeStreamText(text: string): string {
  const held = trailingPartialBreakLength(text);
  const safe = held ? text.slice(0, text.length - held) : text;
  return safe.replaceAll(NEW_MESSAGE_BREAK_TOKEN, "").trim();
}

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
