import { buttonVariants as heroButtonVariants } from "@heroui/react";
import { tv, type VariantProps } from "tailwind-variants";

import { SHAPE_CLASSES } from "./shape";

/**
 * HeroUI's button variants plus GAIA's three, extended the way HeroUI documents.
 * default-solid is v2's bare default button (zinc-700 fill); accent-soft is v2's
 * primary flat button (accent text on an accent tint, via the bridged tokens);
 * default-soft is v2's default flat button (zinc-700 at 40%).
 */
export const buttonVariants = tv({
  extend: heroButtonVariants,
  variants: {
    variant: {
      "default-solid":
        "bg-zinc-700 text-foreground hover:bg-zinc-600 active:bg-zinc-600",
      "default-soft":
        "bg-default-soft text-foreground hover:bg-default-soft-hover active:bg-default-soft-hover",
      "accent-soft":
        "bg-accent-soft text-accent-soft-foreground hover:bg-accent-soft-hover active:bg-accent-soft-hover",
    },
    shape: SHAPE_CLASSES,
  },
  defaultVariants: { shape: "default" },
});

export type ButtonVariants = VariantProps<typeof buttonVariants>;
