/**
 * How every letter moves: the founder letter, a brief's text sheet, the
 * unfolding edition and the folded letter in chat. Documented in DESIGN.md
 * under Animations > Letters.
 */

/**
 * A letter opens unhurried and leaves quickly: an ease-out rise, a short
 * ease-in exit that fades and shrinks it as one. Every letter surface and the
 * page behind it share these timings.
 */
export const LETTER_OPEN_TRANSITION = {
  duration: 0.4,
  ease: [0.33, 1, 0.68, 1],
} as const;
export const LETTER_CLOSE_TRANSITION = {
  duration: 0.2,
  ease: [0.4, 0, 1, 1],
} as const;
export const LETTER_REDUCED_TRANSITION = {
  duration: 0.15,
  ease: "easeOut",
} as const;
/** How far a letter shrinks as it leaves; opacity and scale run on the one curve. */
export const LETTER_EXIT_SCALE = 0.96;

/** A letter opened from chat travels from where it lay, on a long ease-out. */
export const LETTER_TRAVEL_TRANSITION = {
  duration: 0.5,
  ease: [0.32, 0.72, 0, 1],
} as const;
/** Each crease unpeels gently and settles long, so a panel never flips or snaps flat. */
export const LETTER_CREASE_TRANSITION = {
  duration: 0.42,
  ease: [0.5, 0, 0.15, 1],
} as const;
/** The folded letter lifting under the pointer, as a Tailwind timing class. */
export const LETTER_HOVER_EASE = "ease-[cubic-bezier(0.23,1,0.32,1)]";
