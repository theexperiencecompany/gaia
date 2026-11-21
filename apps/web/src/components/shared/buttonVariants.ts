import { buttonVariants as heroButtonVariants } from "@heroui/react";
import { tv, type VariantProps } from "tailwind-variants";

import { SOFT_TINT_CLASSES } from "./controlVariants";
import { SHAPE_CLASSES } from "./shape";
import { TEXT_TONE_CLASSES } from "./tone";

/** The colour a quiet button's text takes on hover; v2 set it per button, so "none" keeps the tone. */
export const BUTTON_HOVER_TONE_CLASSES = {
  none: "",
  foreground: "hover:text-foreground",
  white: "hover:text-white",
  strong: "hover:text-zinc-100",
  bright: "hover:text-zinc-200",
  dim: "hover:text-zinc-300",
  muted: "hover:text-zinc-400",
  accent: "hover:text-accent",
} as const;

export type ButtonHoverTone = keyof typeof BUTTON_HOVER_TONE_CLASSES;

/** Horizontal inset: tight is v2's px-2 compact button, snug a text action on a 4px label inset, none is flush. */
export const BUTTON_INSET_CLASSES = {
  default: "",
  tight: "px-2",
  snug: "px-1",
  none: "p-0",
} as const;

export type ButtonInset = keyof typeof BUTTON_INSET_CLASSES;

const GAIA_DIMENSIONS = {
  shape: SHAPE_CLASSES,
  tone: TEXT_TONE_CLASSES,
  hoverTone: BUTTON_HOVER_TONE_CLASSES,
  inset: BUTTON_INSET_CLASSES,
  tint: SOFT_TINT_CLASSES,
};

const GAIA_DEFAULTS = {
  shape: "default",
  tone: "default",
  hoverTone: "none",
  inset: "default",
  tint: "default",
} as const;

/** Shape, tone, hover tone and inset: the GAIA dimensions layered on any HeroUI button variant. */
export const buttonOverlayVariants = tv({
  variants: GAIA_DIMENSIONS,
  defaultVariants: GAIA_DEFAULTS,
});

/**
 * GAIA's v2 looks HeroUI's Button lacks: default-solid (bare default, zinc-700),
 * default-soft (default flat), accent-soft (primary flat), success-soft and
 * warning-soft (their flat buttons; danger flat is HeroUI's danger-soft) and
 * text (the small inline text action, 4px by 8px, no fill); the rest below.
 */
const GAIA_BUTTON_FILLS = {
  // v2's solid and flat hover kept the fill and dimmed the whole button to 90%
  "default-solid":
    "bg-zinc-700 text-default-foreground hover:opacity-90 active:opacity-90",
  "default-soft":
    "bg-default-soft text-default-soft-foreground hover:opacity-90 active:opacity-90",
  "success-soft":
    "bg-success-soft text-success-soft-foreground hover:opacity-90 active:opacity-90",
  "warning-soft":
    "bg-warning-soft text-warning-soft-foreground hover:opacity-90 active:opacity-90",
  "accent-soft":
    "bg-accent-soft text-accent-soft-foreground hover:opacity-90 active:opacity-90",
  text: "h-auto min-h-0 min-w-0 bg-transparent px-2 py-1 hover:bg-transparent active:bg-transparent",
  // v2's light hover was its flat default fill, zinc-700 at 40%
  quiet: "bg-transparent hover:bg-default-soft active:bg-default-soft",
  // zinc-800 under the pointer and while its editor is open; it holds still on press, as the field it stands for
  property:
    "bg-transparent hover:bg-zinc-800 active:bg-zinc-800 aria-expanded:bg-zinc-800 active:transform-none data-[pressed=true]:bg-zinc-800 data-[pressed=true]:transform-none",
  // a control set into a zinc-800 editor, and one with no fill there
  sunken: "bg-zinc-900 hover:bg-zinc-700 active:bg-zinc-700",
  "raised-ghost": "bg-transparent hover:bg-zinc-700 active:bg-zinc-700",
  // a list row's full-row press target; aria-current marks the row open in the sidebar
  row: "bg-transparent hover:bg-white/[0.04] active:bg-white/[0.04] active:transform-none aria-[current=true]:not-hover:bg-white/[0.06] data-[pressed=true]:transform-none",
} as const;

type GaiaButtonFill = keyof typeof GAIA_BUTTON_FILLS;

export function isGaiaButtonFill(variant: string): variant is GaiaButtonFill {
  return Object.hasOwn(GAIA_BUTTON_FILLS, variant);
}

/** HeroUI's button variants plus GAIA's fills and dimensions, extended the way HeroUI documents. */
export const buttonVariants = tv({
  extend: heroButtonVariants,
  variants: { variant: GAIA_BUTTON_FILLS, ...GAIA_DIMENSIONS },
  defaultVariants: GAIA_DEFAULTS,
});

export type ButtonVariants = VariantProps<typeof buttonVariants>;
