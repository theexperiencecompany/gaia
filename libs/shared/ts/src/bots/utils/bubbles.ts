/**
 * Turns one assistant reply into the bubbles a bot should actually send.
 *
 * The comms prompt asks the model to split its replies with
 * `<NEW_MESSAGE_BREAK>`, and the model mostly does not: across 42 consecutive
 * production replies not one carried an interior sentinel, the median reply was
 * five paragraphs delivered as a single bubble, and the worst was 21 paragraphs
 * and 4,358 characters in one Telegram message. Waiting for the sentinel means
 * shipping essays; this segments deterministically instead.
 *
 * Bots only. The web app splits on the sentinel and renders markdown, where a
 * long reply is a scrollable block rather than a wall in a chat thread.
 *
 * Structure is preserved over aesthetics: a fenced code block, a GFM table, a
 * run of list items and a heading with the block it introduces each stay in one
 * bubble, because splitting them produces output that no longer renders.
 */

import {
  NEW_MESSAGE_BREAK_TOKEN,
  normalizeMessageBreakTokens,
  stripPartialBreakToken,
} from "../../utils/messageBreakUtils";
import { isTableRow } from "./text";

/**
 * A bubble shorter than this is a fragment, not a message ("ok.", "got it."),
 * and reads as a stutter when sent on its own — it joins its neighbour instead.
 */
const MIN_BUBBLE_CHARS = 40;

/** A markdown list item: `- x`, `* x`, `• x`, `1. x`, `2) x`. */
const LIST_ITEM_RE = /^\s*([-*•]|\d+[.)])\s/;
/** An ATX heading: `# x` through `###### x`. */
const HEADING_RE = /^#{1,6}\s/;
/** A whole line wrapped in bold — how this model writes section headings. */
const BOLD_LINE_RE = /^\*\*.+\*\*$/;

function isFenceLine(line: string): boolean {
  return line.trimStart().startsWith("```");
}

/**
 * Splits text at blank lines, except where a blank line is not a boundary:
 * inside a fenced code block it is part of the code.
 */
function splitIntoBlocks(text: string): string[] {
  const blocks: string[] = [];
  let current: string[] = [];
  let inFence = false;

  const close = (): void => {
    if (current.some((line) => line.trim())) blocks.push(current.join("\n"));
    current = [];
  };

  for (const line of text.split("\n")) {
    if (isFenceLine(line)) {
      inFence = !inFence;
      current.push(line);
      continue;
    }
    if (!inFence && !line.trim()) {
      close();
      continue;
    }
    current.push(line);
  }
  close();
  return blocks;
}

function firstLine(block: string): string {
  return block.split("\n", 1)[0] ?? "";
}

function lastLine(block: string): string {
  return block.split("\n").at(-1) ?? "";
}

/**
 * True when `block` only introduces what follows and means nothing alone — a
 * heading, or a single line ending in a colon ("2 reminders, both on WhatsApp:").
 */
function isLeadIn(block: string): boolean {
  const line = block.trim();
  if (line.includes("\n")) return false;
  return HEADING_RE.test(line) || BOLD_LINE_RE.test(line) || line.endsWith(":");
}

/** True when `next` continues `previous` and the two must stay in one bubble. */
function mustJoin(previous: string, next: string): boolean {
  if (isLeadIn(previous)) return true;
  // A loose list: items separated by blank lines are still one list.
  if (
    LIST_ITEM_RE.test(lastLine(previous)) &&
    LIST_ITEM_RE.test(firstLine(next))
  )
    return true;
  // A table whose header got separated from its rows by a stray blank line.
  if (isTableRow(lastLine(previous)) && isTableRow(firstLine(next)))
    return true;
  // A lead-in belongs to what FOLLOWS it. Absorbing it backwards under the
  // fragment rule below would strand the list it introduces in its own bubble.
  if (isLeadIn(next)) return false;
  return next.trim().length < MIN_BUBBLE_CHARS;
}

function mergeBlocks(blocks: string[]): string[] {
  const bubbles: string[] = [];
  for (const block of blocks) {
    const previous = bubbles.at(-1);
    if (previous !== undefined && mustJoin(previous, block)) {
      bubbles[bubbles.length - 1] = `${previous}\n\n${block}`;
      continue;
    }
    bubbles.push(block);
  }
  if (bubbles.length < 2) return bubbles;

  // A short opener has no previous bubble to join, so it merges forward.
  if (bubbles[0].trim().length < MIN_BUBBLE_CHARS || isLeadIn(bubbles[0])) {
    bubbles.splice(0, 2, `${bubbles[0]}\n\n${bubbles[1]}`);
  }
  // A lead-in with nothing after it introduces nothing — send it with the
  // message before it rather than as a dangling one-liner.
  if (bubbles.length > 1 && isLeadIn(bubbles[bubbles.length - 1])) {
    bubbles.splice(
      -2,
      2,
      `${bubbles[bubbles.length - 2]}\n\n${bubbles[bubbles.length - 1]}`,
    );
  }
  return bubbles;
}

/**
 * The bubbles one assistant reply should be delivered as: sentinel-separated
 * segments first (the model's own intent, when it bothers), then paragraphs
 * inside each segment.
 */
export function segmentIntoBubbles(text: string): string[] {
  if (!text.trim()) return [];
  return normalizeMessageBreakTokens(text)
    .split(NEW_MESSAGE_BREAK_TOKEN)
    .flatMap((segment) => {
      const cleaned = stripPartialBreakToken(segment).trim();
      if (!cleaned) return [];
      return mergeBlocks(splitIntoBlocks(cleaned)).map((bubble) =>
        bubble.trim(),
      );
    })
    .filter(Boolean);
}
