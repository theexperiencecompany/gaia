/**
 * The messages a bot sends for bubbles the server already split.
 *
 * The streamed reply and every background delivery (executor results,
 * reminders, workflow results) arrive as bubbles, so a reply is the same
 * messages whichever path carried it.
 */

/** The gap between two bubbles sent back to back, so they land like texts a person sends. */
export const BUBBLE_PAUSE_MS = 600;
