/**
 * Framer Motion timing for the staggered reveal of message-break bubbles.
 *
 * The splitter itself lives in `@shared/utils` and is imported from there
 * directly — re-exporting it here only gave the same function two import paths.
 */

export const MESSAGE_BREAK_STAGGER_SECONDS = 0.08;
export const MESSAGE_BREAK_DURATION_SECONDS = 0.25;
export const MESSAGE_BREAK_EASE_OUT_QUART: [number, number, number, number] = [
  0.25, 1, 0.5, 1,
];
