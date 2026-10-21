/**
 * Turns one assistant reply into the bubbles a bot should actually send.
 *
 * The model owns the splits: it must emit `<NEW_MESSAGE_BREAK>` between
 * bubbles, and nothing here invents splits it did not ask for. A reply with
 * no sentinel ships as ONE bubble. Blank-line segmentation was removed on
 * purpose: it shredded logical markdown (lists, tables, headings parted from
 * their blocks) and no merge heuristic could reconstruct intent the model
 * never stated.
 *
 * Bots only. The web app splits on the sentinel and renders markdown, where a
 * long reply is a scrollable block rather than a wall in a chat thread.
 */

import {
  NEW_MESSAGE_BREAK_TOKEN,
  normalizeMessageBreakTokens,
  stripPartialBreakToken,
} from "../../utils/messageBreakUtils";

/**
 * A bubble shorter than this is a fragment, not a message ("ok.", "got it."),
 * and reads as a stutter when sent on its own — it joins its neighbour instead.
 */
const MIN_BUBBLE_CHARS = 40;

/**
 * Split on the sentinel everywhere except inside fenced code blocks, where a
 * stray token would break the code. The token is swallowed there (replaced
 * with a newline) rather than splitting.
 */
function splitOutsideFences(text: string): string[] {
  const parts = text.split(NEW_MESSAGE_BREAK_TOKEN);
  const out: string[] = [];
  let current = "";
  let inFence = false;
  parts.forEach((part, i) => {
    current += part;
    if ((part.match(/```/g) ?? []).length % 2 === 1) inFence = !inFence;
    if (inFence && i < parts.length - 1) {
      current += "\n";
    } else {
      out.push(current);
      current = "";
    }
  });
  return out;
}

/** Fold sub-message fragments into their neighbour so no bubble stutters. */
function mergeFragments(pieces: string[]): string[] {
  const bubbles: string[] = [];
  for (const piece of pieces) {
    const previous = bubbles.at(-1);
    if (previous !== undefined && previous.trim().length < MIN_BUBBLE_CHARS) {
      bubbles[bubbles.length - 1] = `${previous}\n\n${piece}`;
      continue;
    }
    bubbles.push(piece);
  }
  const last = bubbles.at(-1);
  if (
    bubbles.length > 1 &&
    last !== undefined &&
    last.trim().length < MIN_BUBBLE_CHARS
  ) {
    bubbles.splice(-2, 2, `${bubbles.at(-2)}\n\n${last}`);
  }
  return bubbles;
}

/**
 * The bubbles one assistant reply should be delivered as: the model's own
 * sentinel-separated segments, nothing more. No sentinel means one bubble.
 */
export function segmentIntoBubbles(text: string): string[] {
  if (!text.trim()) return [];
  const segments = splitOutsideFences(normalizeMessageBreakTokens(text));
  const cleaned = segments
    .map((segment) => stripPartialBreakToken(segment).trim())
    .filter(Boolean);
  return mergeFragments(cleaned);
}
