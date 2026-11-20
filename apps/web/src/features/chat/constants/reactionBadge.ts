/**
 * Tapback geometry, taken from the "iMessage Reactions" Figma export. The
 * export draws the badge 102 units tall (3x), so every length below is the
 * Figma value times `FIGMA_TO_PX`, giving a 34px badge.
 */
const FIGMA_BADGE_HEIGHT = 102;
export const REACTION_BADGE_HEIGHT_PX = 34;
const FIGMA_TO_PX = REACTION_BADGE_HEIGHT_PX / FIGMA_BADGE_HEIGHT;

interface TailDot {
  size: number;
  /** Distance from the badge's tail-side edge to the dot's nearest edge; negative hangs past it. */
  edge: number;
  top: number;
}

/** The badge's tail: a 30-unit lobe fused to the circle, plus a 16-unit dot. */
export const REACTION_TAIL: readonly TailDot[] = [
  {
    size: 30 * FIGMA_TO_PX,
    edge: -1.5 * FIGMA_TO_PX,
    top: 73.5 * FIGMA_TO_PX,
  },
  {
    size: 16 * FIGMA_TO_PX,
    edge: -14.5 * FIGMA_TO_PX,
    top: 98.5 * FIGMA_TO_PX,
  },
];

/**
 * Ring in the page background that cuts the badge body out of the bubble. The
 * Figma hairline (1 unit, ~0.33px) disappears against a bubble, so it is widened.
 */
export const REACTION_RING_PX = 2;

/** Glyph is 46 of 102 units in the Figma single badge. */
export const REACTION_EMOJI_PX = Math.round(46 * FIGMA_TO_PX);

/** Neutral zinc, so the badge separates from the cyan user bubble it sits on. */
export const REACTION_FILL_CLASS = "bg-zinc-700";

/**
 * How far the badge hangs above and past the bubble's corner. Chosen so the
 * tail lands in the bubble's 20px side padding instead of on the text.
 */
export const REACTION_OVERHANG_TOP_PX = 26;
export const REACTION_OVERHANG_SIDE_PX = 22;
