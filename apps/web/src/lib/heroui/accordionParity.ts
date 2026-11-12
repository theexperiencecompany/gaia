/**
 * HeroUI v2 accordion slot styling on the v3 Accordion compounds (theme 2.4.26).
 * v2 had no trigger padding-x or hover fill, a left chevron turning down when open,
 * and padded content; v3 defaults to px-4, a hover fill, a down/up chevron and a bare panel.
 */

/** v2 `light` (default) variant root padding. */
export const ACCORDION_ROOT = "px-2";
/** v2 `shadow` variant root (dark: content1 fill, shadow-medium). */
export const ACCORDION_ROOT_SHADOW =
  "rounded-medium bg-content1 px-4 shadow-[0_0_15px_0_rgb(0_0_0/0.06),0_2px_30px_0_rgb(0_0_0/0.22),inset_0_0_1px_0_rgb(255_255_255/0.15)]";

/** Trigger without vertical padding, for v2 sites that overrode the trigger's py. */
export const ACCORDION_TRIGGER_BASE = "gap-3 px-0 hover:bg-transparent";
export const ACCORDION_TRIGGER = `${ACCORDION_TRIGGER_BASE} py-4`;
/** v2 `isCompact` trigger. */
export const ACCORDION_TRIGGER_COMPACT = `${ACCORDION_TRIGGER_BASE} py-2`;

export const ACCORDION_INDICATOR =
  "rotate-90 text-default-400 data-[expanded=true]:rotate-0";

export const ACCORDION_PANEL = "py-2";
/** v2 `isCompact` content. */
export const ACCORDION_PANEL_COMPACT = "py-1";
