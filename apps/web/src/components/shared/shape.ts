import { tv } from "tailwind-variants";

/**
 * The one corner-shape dimension every HeroUI control takes. "default" is the
 * control's own radius for its size (gaia.css); sharp (2px), sm (8px), md (12px),
 * lg (14px) and xl (16px) fix the radius whatever the size, as v2's radius prop did; pill
 * fully rounds it. One class each in gaia.css, for Button, Chip, ButtonGroup,
 * Tabs, Checkbox and the field controls.
 */
export const SHAPE_CLASSES = {
  default: "",
  sharp: "gaia-sharp",
  sm: "gaia-radius-sm",
  md: "gaia-radius-md",
  lg: "gaia-radius-lg",
  xl: "gaia-radius-xl",
  pill: "gaia-pill",
} as const;

export type Shape = keyof typeof SHAPE_CLASSES;

export const shapeVariants = tv({
  variants: { shape: SHAPE_CLASSES },
  defaultVariants: { shape: "default" },
});
