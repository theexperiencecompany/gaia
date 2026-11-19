import type { Variants } from "motion/react";

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

/**
 * A sheet tilts and settles onto the screen, then leaves by fading and
 * shrinking in place. Reduced motion gets a plain fade both ways.
 */
export const LETTER_SHEET_VARIANTS: Record<"full" | "reduced", Variants> = {
  full: {
    arrive: { opacity: 0, scale: 0.95, rotate: 1, y: 22 },
    enter: {
      opacity: 1,
      scale: 1,
      rotate: 0,
      y: 0,
      transition: LETTER_OPEN_TRANSITION,
    },
    exit: {
      opacity: 0,
      scale: LETTER_EXIT_SCALE,
      transition: LETTER_CLOSE_TRANSITION,
    },
  },
  reduced: {
    arrive: { opacity: 0 },
    enter: { opacity: 1, transition: LETTER_REDUCED_TRANSITION },
    exit: { opacity: 0, transition: LETTER_REDUCED_TRANSITION },
  },
};
