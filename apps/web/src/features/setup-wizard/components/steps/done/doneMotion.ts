import type { Transition, Variants } from "motion/react";

/** Each Done-step card rises in as its parent's stagger reaches it. */
export const CARD_VARIANTS: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0 },
};

export const CARD_TRANSITION: Transition = {
  duration: 0.4,
  ease: [0.19, 1, 0.22, 1],
};

/** A line inside a card: a shorter rise than the card itself. */
export const ITEM_VARIANTS: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
};
