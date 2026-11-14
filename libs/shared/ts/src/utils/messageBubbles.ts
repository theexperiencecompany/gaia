/**
 * The one splitter that turns assistant text into the bubbles the model asked for.
 *
 * Web, the streamed bot reply and the bots' background deliveries all split
 * here, so a reply reads as the same bubbles live, after a reload and on every
 * platform. The model owns the splits: nothing here invents one or merges two.
 */

import {
  NEW_MESSAGE_BREAK_TOKEN,
  normalizeMessageBreakTokens,
  stripPartialBreakToken,
} from "./messageBreakUtils";
import { openUIBlockRanges } from "./openui-parser";

const CODE_FENCE = "```";

/** Ranges `[start, end)` of every ``` code block, an unclosed one running to the end. */
function codeFenceRanges(text: string): [number, number][] {
  const ranges: [number, number][] = [];
  let open = text.indexOf(CODE_FENCE);
  while (open !== -1) {
    const close = text.indexOf(CODE_FENCE, open + CODE_FENCE.length);
    if (close === -1) {
      ranges.push([open, text.length]);
      break;
    }
    ranges.push([open, close + CODE_FENCE.length]);
    open = text.indexOf(CODE_FENCE, close + CODE_FENCE.length);
  }
  return ranges;
}

/**
 * Cuts text at every break outside a code block or :::openui block, untrimmed.
 * A break inside one would bisect it, so it becomes a newline instead.
 */
function cutAtBreaks(text: string): string[] {
  const normalized = normalizeMessageBreakTokens(text);
  const fenced = [
    ...codeFenceRanges(normalized),
    ...openUIBlockRanges(normalized),
  ];
  const pieces: string[] = [];
  let piece = "";
  let cursor = 0;
  let at = normalized.indexOf(NEW_MESSAGE_BREAK_TOKEN);
  while (at !== -1) {
    piece += normalized.slice(cursor, at);
    cursor = at + NEW_MESSAGE_BREAK_TOKEN.length;
    const breakAt = at;
    if (fenced.some(([start, end]) => breakAt >= start && breakAt < end)) {
      piece += "\n";
    } else {
      pieces.push(piece);
      piece = "";
    }
    at = normalized.indexOf(NEW_MESSAGE_BREAK_TOKEN, cursor);
  }
  pieces.push(piece + normalized.slice(cursor));
  return pieces;
}

const cleanBubble = (piece: string): string =>
  stripPartialBreakToken(piece).trim();

/** The non-empty bubbles of cut pieces, cleaned. */
const cleanBubbles = (pieces: string[]): string[] =>
  pieces.flatMap((piece) => {
    const bubble = cleanBubble(piece);
    return bubble ? [bubble] : [];
  });

/** Split finished assistant text into its bubbles; empty ones are dropped. */
export function splitMessageByBreaks(text: string): string[] {
  return cleanBubbles(cutAtBreaks(text));
}

/** Text still streaming, as the bubbles a break has closed and the one still being written. */
export interface StreamingBubbles {
  complete: string[];
  open: string;
}

/**
 * Split text that is still streaming. A complete bubble never changes again, and
 * the open one only grows; a half-received break is never part of either.
 */
export function splitStreamingBubbles(text: string): StreamingBubbles {
  const pieces = cutAtBreaks(text);
  const open = cleanBubble(pieces.pop() ?? "");
  return { complete: cleanBubbles(pieces), open };
}
