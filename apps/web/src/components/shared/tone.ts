import { tv } from "tailwind-variants";

/**
 * The one text-colour dimension for HeroUI content and controls: white, then
 * v2's zinc steps from brightest to darkest, and the accent. Buttons pair it
 * with hoverTone (buttonVariants.ts), fields with placeholder (controlVariants.ts).
 */
export const TEXT_TONE_CLASSES = {
  default: "",
  white: "text-white",
  strong: "text-zinc-100",
  bright: "text-zinc-200",
  dim: "text-zinc-300",
  muted: "text-zinc-400",
  faint: "text-zinc-500",
  subtle: "text-zinc-600",
  ghost: "text-zinc-700",
  accent: "text-accent",
} as const;

export type TextTone = keyof typeof TEXT_TONE_CLASSES;

/** interactive: the quiet text brightens to the foreground on hover (v2's muted menu items). */
export const toneVariants = tv({
  variants: {
    tone: TEXT_TONE_CLASSES,
    interactive: { true: "transition hover:text-foreground", false: "" },
  },
  defaultVariants: { tone: "default", interactive: false },
});
