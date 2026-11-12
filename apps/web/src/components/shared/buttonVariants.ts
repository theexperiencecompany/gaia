import { buttonVariants as heroButtonVariants } from "@heroui/react";
import { tv, type VariantProps } from "tailwind-variants";

/**
 * HeroUI's button variants plus GAIA's two, extended the way HeroUI documents.
 * default-solid is v2's bare default button (zinc-700 fill); accent-soft is v2's
 * primary flat button (accent text on an accent tint, via the bridged tokens).
 */
export const buttonVariants = tv({
  extend: heroButtonVariants,
  variants: {
    variant: {
      "default-solid":
        "bg-zinc-700 text-foreground hover:bg-zinc-600 active:bg-zinc-600",
      "accent-soft":
        "bg-accent-soft text-accent-soft-foreground hover:bg-accent-soft-hover active:bg-accent-soft-hover",
    },
  },
});

export type ButtonVariants = VariantProps<typeof buttonVariants>;
