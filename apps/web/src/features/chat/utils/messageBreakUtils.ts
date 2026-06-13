/**
 * Utility functions for handling NEW_MESSAGE_BREAK tokens in chat messages
 * Enables WhatsApp-style multiple bubble responses from a single message
 */

export { splitMessageByBreaks } from "@shared/utils";

/** Framer Motion timing for staggered message-break bubble reveals. */
export const MESSAGE_BREAK_STAGGER_SECONDS = 0.08;
export const MESSAGE_BREAK_DURATION_SECONDS = 0.25;
export const MESSAGE_BREAK_EASE_OUT_QUART: [number, number, number, number] = [
  0.25, 1, 0.5, 1,
];
