/**
 * Shared composer constants — headless, UI-agnostic.
 *
 * Single source of truth for composer chrome so web (rounded-3xl) and
 * mobile (rounded ~20) converge on one token set. Values are platform
 * independent — consumers apply them via their own style system
 * (Tailwind, React Native, CSS, etc).
 *
 * - radius: 24 — matches web `rounded-3xl` (1.5rem = 24px) and the
 *   desktop island COMPOSER_CORNER_RADIUS = 24. Mobile moderates to
 *   ~20 on small screens but uses this as the canonical token.
 * - bg: "#27272a" — zinc-800, the composer pill background on both
 *   web (`bg-zinc-800`) and mobile (`colors.zinc800`).
 * - maxRows: 13 — web ComposerInput `maxRows={13}`; mobile caps at 5
 *   lines visually but the shared limit is 13 so the data layer is
 *   consistent (UI can clamp to 5 if desired).
 */

export const COMPOSER_CONSTANTS = {
  /** Corner radius in pixels — `rounded-3xl` */
  radius: 24,
  /** Composer pill background — zinc-800 */
  bg: "#27272a",
  /** Tailwind class for the same bg (convenience) */
  bgClass: "bg-zinc-800",
  /** Maximum visible rows before scrolling */
  maxRows: 13,
  /** Minimum rows (collapsed) */
  minRows: 1,
  /** Placeholder shown when empty */
  placeholder: "What can I do for you today? (Type '/' for tools)",
  /** Hard character limit */
  maxLength: 4000,
  /** Vertical padding tokens (mirrors web `px-1 pt-1 pb-2`) */
  padding: {
    horizontal: 4,
    top: 4,
    bottom: 8,
  },
} as const;

export type ComposerConstants = typeof COMPOSER_CONSTANTS;
