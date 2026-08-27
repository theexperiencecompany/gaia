import { POSITION_CALC } from "./constants";
import type { HoloCardDisplayData } from "./types";

interface BackgroundPosition {
  lp: number;
  tp: number;
}

/**
 * Calculates the background position based on cursor/touch position
 * @param offsetX - X offset from the element
 * @param offsetY - Y offset from the element
 * @param width - Element width
 * @param height - Element height
 * @returns Background position object with lp (left percent) and tp (top percent)
 */
export function calculateBackgroundPosition(
  offsetX: number,
  offsetY: number,
  width: number,
  height: number,
): BackgroundPosition {
  const px = Math.abs(Math.floor((100 / width) * offsetX) - 100);
  const py = Math.abs(Math.floor((100 / height) * offsetY) - 100);

  const lp = 50 + (px - 50) / POSITION_CALC.DAMPING_FACTOR;
  const tp = 50 + (py - 50) / POSITION_CALC.DAMPING_FACTOR;

  return { lp, tp };
}

// Fold a freshly-arrived card into the copy being edited.
//
// The card renders the EDITED copy, not `initialData`, so every field of the
// incoming card has to come through: a refetch rewrites name, bio, account
// number and member_since — connecting Gmail replaces the placeholder bio with
// a generated one — and a version of this that patched only the overlay fields
// froze everything else at whatever it was on first mount.
//
// The overlay is the one exception. A refetch must not yank it out from under
// someone mid-pick, so the incoming overlay wins only where it actually differs
// from the card we last saw; otherwise the local choice stands.
export function mergeIncomingCard(
  edited: HoloCardDisplayData,
  incoming: HoloCardDisplayData,
  previousIncoming: HoloCardDisplayData,
): HoloCardDisplayData {
  return {
    ...incoming,
    overlay_color:
      incoming.overlay_color !== previousIncoming.overlay_color
        ? incoming.overlay_color
        : edited.overlay_color,
    overlay_opacity:
      incoming.overlay_opacity !== previousIncoming.overlay_opacity
        ? incoming.overlay_opacity
        : edited.overlay_opacity,
  };
}
