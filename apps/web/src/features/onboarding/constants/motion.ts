/**
 * Shared Motion (Framer) presets used across onboarding stages and composers.
 * Centralised so timing/easing tweaks land in one place. The easing curve
 * `EASE_OUT_QUART = [0.19, 1, 0.22, 1]` is the global onboarding curve.
 */

import type { Transition } from "motion/react";

export const EASE_OUT_QUART: [number, number, number, number] = [
  0.19, 1, 0.22, 1,
];

/** Standard 0.4s fade-up — used for entrance of most onboarding elements. */
export const MOTION_FADE_UP = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
} as const;

/** Same as MOTION_FADE_UP but slightly longer travel — for top-level stage roots. */
export const MOTION_FADE_UP_LARGE = {
  initial: { opacity: 0, y: 15 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
} as const;

/** Subtle entrance — for things that animate in below an already-visible parent. */
export const MOTION_FADE_UP_SUBTLE = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
} as const;

/** Centered CTA composer entrance — short delay so it lands after content. */
export const MOTION_COMPOSER_CTA = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: {
    delay: 0.3,
    duration: 0.35,
    ease: EASE_OUT_QUART,
  } satisfies Transition,
} as const;

/** Streaming chat message entrance. */
export const MOTION_STREAM_MESSAGE = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: EASE_OUT_QUART } satisfies Transition,
} as const;
