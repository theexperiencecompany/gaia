/**
 * Utility functions for handling NEW_MESSAGE_BREAK tokens in chat messages
 * Enables WhatsApp-style multiple bubble responses from a single message
 *
 * The Python half is `apps/api/app/utils/message_breaks.py` — both sides must
 * accept the same spellings, or a sentinel split on one surface ships as
 * literal text on the other.
 */

/**
 * The literal sentinel the LLM emits to signal "split into a new bubble here".
 * Single source of truth — every consumer (bot streaming, frontend rendering,
 * message persistence) should reference this constant rather than duplicating
 * the string.
 */
export const NEW_MESSAGE_BREAK_TOKEN = "<NEW_MESSAGE_BREAK>";
export const NEW_MESSAGE_BREAK_TOKEN_LENGTH = NEW_MESSAGE_BREAK_TOKEN.length;

/**
 * Words of each spelling the model actually emits, in order. Everything around
 * and between them is matched leniently: `<` or `[` to open, an optional `/` on
 * either side, and `_`, `-`, a space or nothing at all between the words. The
 * pattern used to accept only `<NEW_MESSAGE_BREAK>` and `<NEW_LINE_BREAK>`, so
 * `[NEW_MESSAGE_BREAK]` and `</NEW_MESSAGE_BREAK>` shipped as literal text.
 */
const SENTINEL_WORD_SEQUENCES: readonly (readonly string[])[] = [
  ["NEW", "MESSAGE", "BREAK"],
  ["NEW", "LINE", "BREAK"],
];

const SEPARATOR = "[\\s_-]*";
const OPEN = "[<\\[]\\s*/?\\s*";
const CLOSE = "\\s*/?\\s*[>\\]]";

const SENTINEL_BODY = SENTINEL_WORD_SEQUENCES.map((words) =>
  words.join(SEPARATOR),
).join("|");

const MESSAGE_BREAK_VARIANT_PATTERN = new RegExp(
  `${OPEN}(?:${SENTINEL_BODY})${CLOSE}`,
  "gi",
);

/** Regex matching any non-empty prefix of `word` (`N`, `NE`, `NEW`). */
function wordPrefixes(word: string): string {
  let pattern = "";
  for (const char of [...word].reverse()) {
    pattern = pattern ? `${char}(?:${pattern})?` : char;
  }
  return pattern;
}

/** Regex matching any non-empty prefix of one whole spelling, separators included. */
function partialSequence(words: readonly string[]): string {
  let pattern = "";
  for (const word of [...words.slice(1)].reverse()) {
    const inner = pattern ? `(?:${pattern})?` : "";
    pattern = `${SEPARATOR}(?:${wordPrefixes(word)}${inner})?`;
  }
  return `${wordPrefixes(words[0])}(?:${pattern})?`;
}

const PARTIAL_BODY = SENTINEL_WORD_SEQUENCES.map(partialSequence).join("|");

/**
 * A sentinel a chunk boundary cut in half, anchored to the end of the text.
 *
 * The `<` form also matches on its own: an unclosed `<` is far more likely to be
 * the first byte of a sentinel than real content, and it is what breaks a
 * Telegram HTML edit. The `[` form requires at least one character of the
 * spelling, because a lone trailing `[` is usually the start of a markdown link.
 */
const PARTIAL_SENTINEL_RE = new RegExp(
  `(?:<\\s*/?\\s*(?:${PARTIAL_BODY})?|\\[\\s*/?\\s*(?:${PARTIAL_BODY}))$`,
  "i",
);

/**
 * Rewrites every break-sentinel spelling to the canonical token, so downstream
 * splitting only ever has to match {@link NEW_MESSAGE_BREAK_TOKEN}.
 */
export function normalizeMessageBreakTokens(text: string): string {
  return text.replace(MESSAGE_BREAK_VARIANT_PATTERN, NEW_MESSAGE_BREAK_TOKEN);
}

/**
 * Drops a trailing partial break sentinel.
 *
 * The token arrives split across stream chunks, so a half-received
 * `<NEW_MESSAG` would otherwise flash in the bubble as literal text — and on
 * Telegram an unclosed `<` makes the whole HTML edit fail to parse. This also
 * runs on FINAL text: a reply whose last chunk is `…numbers<NEW_MESSAGE_B` (the
 * model was cut off mid-sentinel) has no later chunk to hide the fragment, so
 * without this the fragment is what the user reads.
 */
export function stripPartialBreakToken(text: string): string {
  return text.replace(PARTIAL_SENTINEL_RE, "");
}
