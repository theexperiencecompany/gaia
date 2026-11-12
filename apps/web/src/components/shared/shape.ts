import { tv } from "tailwind-variants";

/**
 * The one corner-shape dimension every HeroUI control takes: "default" is the
 * radius from the gaia layer in base.css, "pill" fully rounds it. The gaia-pill
 * class is defined once there for Button, Chip, Tabs, field controls, Checkbox
 * and ButtonGroup.
 */
export const SHAPE_CLASSES = { default: "", pill: "gaia-pill" } as const;

export type Shape = keyof typeof SHAPE_CLASSES;

export const shapeVariants = tv({
  variants: { shape: SHAPE_CLASSES },
  defaultVariants: { shape: "default" },
});
