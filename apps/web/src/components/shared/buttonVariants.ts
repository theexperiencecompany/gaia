import { buttonVariants as heroButtonVariants } from "@heroui/react";
import { tv, type VariantProps } from "tailwind-variants";

import { SHAPE_CLASSES } from "./shape";
import { TEXT_TONE_CLASSES, type TextTone } from "./tone";

/** The colour a quiet button's text takes on hover; v2 set it per button, so "none" keeps the tone. */
export const BUTTON_HOVER_TONE_CLASSES = {
  none: "",
  foreground: "hover:text-foreground",
  dim: "hover:text-zinc-300",
  muted: "hover:text-zinc-400",
  accent: "hover:text-accent",
} as const;

export type ButtonHoverTone = keyof typeof BUTTON_HOVER_TONE_CLASSES;

/** Horizontal inset: tight is v2's px-2 compact button, none is a flush text action. */
export const BUTTON_INSET_CLASSES = {
  default: "",
  tight: "px-2",
  none: "p-0",
} as const;

export type ButtonInset = keyof typeof BUTTON_INSET_CLASSES;

export type ButtonTone = TextTone;

const GAIA_DIMENSIONS = {
  shape: SHAPE_CLASSES,
  tone: TEXT_TONE_CLASSES,
  hoverTone: BUTTON_HOVER_TONE_CLASSES,
  inset: BUTTON_INSET_CLASSES,
};

const GAIA_DEFAULTS = {
  shape: "default",
  tone: "default",
  hoverTone: "none",
  inset: "default",
} as const;

/** Shape, tone, hover tone and inset: the GAIA dimensions layered on any HeroUI button variant. */
export const buttonOverlayVariants = tv({
  variants: GAIA_DIMENSIONS,
  defaultVariants: GAIA_DEFAULTS,
});

/**
 * HeroUI's button variants plus GAIA's v2 looks: default-solid (bare default,
 * zinc-700), default-soft (default flat), accent-soft (primary flat),
 * success-soft and warning-soft (their flat buttons; danger flat is HeroUI's
 * danger-soft), and text (the small inline text action, 4px by 8px, no fill).
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
      text: "h-auto min-h-0 min-w-0 bg-transparent px-2 py-1 hover:bg-transparent active:bg-transparent",
    },
    ...GAIA_DIMENSIONS,
  },
  defaultVariants: GAIA_DEFAULTS,
});

export type ButtonVariants = VariantProps<typeof buttonVariants>;
