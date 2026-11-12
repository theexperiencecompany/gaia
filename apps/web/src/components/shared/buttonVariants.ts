import { buttonVariants as heroButtonVariants } from "@heroui/react";
import { tv, type VariantProps } from "tailwind-variants";

import { SHAPE_CLASSES } from "./shape";

/**
 * HeroUI's button variants plus GAIA's, extended the way HeroUI documents.
 * default-solid is v2's bare default button (zinc-700 fill); accent-soft is v2's
 * primary flat button (accent text on an accent tint, via the bridged tokens);
 * default-soft is v2's default flat button (zinc-700 at 40%); success-soft and
 * warning-soft are v2's success/warning flat buttons (danger flat is HeroUI's
 * own danger-soft, which reads the same bridged tokens).
 */
export const buttonVariants = tv({
  extend: heroButtonVariants,
  variants: {
    variant: {
      "default-solid":
        "bg-zinc-700 text-foreground hover:bg-zinc-600 active:bg-zinc-600",
      "default-soft":
        "bg-default-soft text-foreground hover:bg-default-soft-hover active:bg-default-soft-hover",
      "success-soft":
        "bg-success-soft text-success-soft-foreground hover:bg-success-soft-hover active:bg-success-soft-hover",
      "warning-soft":
        "bg-warning-soft text-warning-soft-foreground hover:bg-warning-soft-hover active:bg-warning-soft-hover",
      "accent-soft":
        "bg-accent-soft text-accent-soft-foreground hover:bg-accent-soft-hover active:bg-accent-soft-hover",
    },
    shape: SHAPE_CLASSES,
  },
  defaultVariants: { shape: "default" },
});

export type ButtonVariants = VariantProps<typeof buttonVariants>;
