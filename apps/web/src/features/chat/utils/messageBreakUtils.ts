import { splitMessageByBreaks } from "@shared/utils";

/**
 * Framer Motion timing for the staggered reveal of message-break bubbles.
 *
 * The splitter itself lives in `@shared/utils` and is imported from there
 * directly — re-exporting it here only gave the same function two import paths.
 */

const MESSAGE_BREAK_STAGGER_SECONDS = 0.08;
export const MESSAGE_BREAK_DURATION_SECONDS = 0.25;
export const MESSAGE_BREAK_EASE_OUT_QUART: [number, number, number, number] = [
  0.25, 1, 0.5, 1,
];

/** How the parts of one bot turn land: the gap between consecutive parts and
 *  how long each takes. Chat's default is a quick ripple; onboarding slows it
 *  to a typed cadence. */
export interface PartChoreography {
  staggerSeconds: number;
  durationSeconds: number;
}

export const DEFAULT_PART_CHOREOGRAPHY: PartChoreography = {
  staggerSeconds: MESSAGE_BREAK_STAGGER_SECONDS,
  durationSeconds: MESSAGE_BREAK_DURATION_SECONDS,
};

/** The choreography a bubble should use: the caller's, or chat's default.
 *  A function rather than a destructuring default so the bubble component
 *  itself carries no extra branch. */
export function resolvePartChoreography(
  choreography: PartChoreography | undefined,
): PartChoreography {
  return choreography ?? DEFAULT_PART_CHOREOGRAPHY;
}

/** How long the avatar waits before fading in: it belongs to the last part of
 *  the turn, so it lands with that part rather than with the first. */
export function logoDelayFor(
  cleanText: string,
  staggerSeconds: number,
): number {
  if (!cleanText) return 0;
  const parts = splitMessageByBreaks(cleanText);
  return Math.max(0, parts.length - 1) * staggerSeconds;
}
