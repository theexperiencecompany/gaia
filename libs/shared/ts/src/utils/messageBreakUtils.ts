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
 * Every spelling of the sentinel the model actually emits. `<NEW_LINE_BREAK>`
 * is the common near-miss; only the exact canonical token used to be split on,
 * so variants shipped to platforms as literal text.
 */
const BREAK_TOKEN_SPELLINGS = ["<NEW_MESSAGE_BREAK>", "<NEW_LINE_BREAK>"];

const MESSAGE_BREAK_VARIANT_PATTERN = /<\s*NEW_(?:MESSAGE|LINE)_BREAK\s*>/gi;

/**
 * Rewrites every break-sentinel spelling to the canonical token, so downstream
 * splitting only ever has to match {@link NEW_MESSAGE_BREAK_TOKEN}.
 */
export function normalizeMessageBreakTokens(text: string): string {
  return text.replace(MESSAGE_BREAK_VARIANT_PATTERN, NEW_MESSAGE_BREAK_TOKEN);
}

/** True when the text holds any complete break-sentinel spelling. */
export function containsMessageBreakToken(text: string): boolean {
  return /<\s*NEW_(?:MESSAGE|LINE)_BREAK\s*>/i.test(text);
}

/**
 * Every proper prefix of every sentinel spelling, longest first. A chunk
 * boundary can land anywhere inside a variant too ("<new_line_bre",
 * "< NEW_LINE_BR"), so the live-preview strip has to recognize partial
 * spellings case-insensitively, with the same optional whitespace after "<"
 * that {@link MESSAGE_BREAK_VARIANT_PATTERN} accepts in complete tokens.
 */
const PARTIAL_SENTINEL_SUFFIXES = [
  ...new Set(
    BREAK_TOKEN_SPELLINGS.flatMap((spelling) => {
      const core = spelling.slice(1); // drop "<"
      const prefixes: string[] = [];
      for (let n = 0; n < core.length; n += 1) prefixes.push(core.slice(0, n));
      return prefixes;
    }),
  ),
]
  .filter((prefix) => prefix.length > 0)
  .sort((a, b) => b.length - a.length);

const PARTIAL_SENTINEL_RE = new RegExp(
  `<\\s*(?:${PARTIAL_SENTINEL_SUFFIXES.map((p) => p.toLowerCase()).join("|")})?$`,
  "i",
);

/**
 * Drops a trailing partial break sentinel from live-preview text.
 *
 * The token arrives split across stream chunks, so a half-received
 * `<NEW_MESSAG` would otherwise flash in the bubble as literal text — and on
 * Telegram an unclosed ``<`` makes the whole HTML edit fail to parse. Runs on
 * already-normalized text, but recognizes partial variants of any casing so a
 * chunk boundary landing mid-spelling never flashes either.
 */
export function stripPartialBreakToken(text: string): string {
  return text.replace(PARTIAL_SENTINEL_RE, "");
}
