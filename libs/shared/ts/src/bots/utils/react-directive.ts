/**
 * The comms `<EMOJI>👍</EMOJI>` control tag, as the bot streamer must see it.
 *
 * The rule is the backend's `interpret_comms_output` (apps/api/app/agents/core/
 * comms_directive.py): once break tokens split the turn, it is exactly one bubble,
 * and that bubble is the tag (any case) around a non-empty emoji. The pre-tag
 * `REACT: <emoji>` line is still read, because comms' own history carries it.
 * Only a turn matching it gets an `emoji_ack`; anything else is sent as a reply.
 */
import {
  NEW_MESSAGE_BREAK_TOKEN,
  normalizeMessageBreakTokens,
  stripPartialBreakToken,
} from "../../utils/messageBreakUtils";

const EMOJI_OPEN_TAG = "<EMOJI>";
const LEGACY_REACT_KEYWORD = "REACT:";

/** `[^\n]` rather than `.`: Python's `.` excludes only `\n`, JS's also `\r` and U+2028/9. */
const EMOJI_TAG_PATTERN = /^<EMOJI>([^\n]*?)<\/EMOJI>$/i;
const LEGACY_REACT_PATTERN = /^REACT:([^\n]*)$/i;

function turnBubbles(turnText: string): string[] {
  return normalizeMessageBreakTokens(turnText)
    .split(NEW_MESSAGE_BREAK_TOKEN)
    .map((part) => stripPartialBreakToken(part).trim())
    .filter(Boolean);
}

/** The emoji a whole turn reacts with, or null when the backend treats it as a reply. */
export function reactDirectiveEmoji(turnText: string): string | null {
  const bubbles = turnBubbles(turnText);
  if (bubbles.length !== 1) return null;
  const match =
    EMOJI_TAG_PATTERN.exec(bubbles[0]) ?? LEGACY_REACT_PATTERN.exec(bubbles[0]);
  const emoji = match?.[1].trim();
  return emoji || null;
}

function startsLike(candidate: string, prefix: string): boolean {
  return prefix.startsWith(candidate.slice(0, prefix.length).toUpperCase());
}

/**
 * Whether a turn streamed so far could still end as an emoji directive — the
 * text the streamer must hold back until the `emoji_ack` or the end of the turn.
 */
export function couldBecomeReactDirective(turnText: string): boolean {
  const candidate = turnText.trimStart();
  if (
    !startsLike(candidate, EMOJI_OPEN_TAG) &&
    !startsLike(candidate, LEGACY_REACT_KEYWORD)
  ) {
    return false;
  }
  // Past a newline only trailing whitespace may follow, so the turn is final.
  if (!candidate.includes("\n")) return true;
  return reactDirectiveEmoji(candidate) !== null;
}
