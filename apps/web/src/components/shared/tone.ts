import { tv } from "tailwind-variants";

/**
 * The one text-tone dimension for quiet HeroUI content (Chip, Chip.Label, a
 * list Header, an Accordion.Panel): v2's zinc greys and the accent. Buttons
 * take the same tones with a hover step (buttonVariants.ts).
 */
export const TEXT_TONE_CLASSES = {
  default: "",
  dim: "text-zinc-300",
  muted: "text-zinc-400",
  faint: "text-zinc-500",
  accent: "text-accent",
} as const;

export type TextTone = keyof typeof TEXT_TONE_CLASSES;

export const toneVariants = tv({
  variants: { tone: TEXT_TONE_CLASSES },
  defaultVariants: { tone: "default" },
});
