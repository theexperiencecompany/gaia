import { tv, type VariantProps } from "tailwind-variants";

/**
 * A card's fill by where it sits: "raised" (zinc-800) on the page background or a
 * zinc-900 panel, "inset" (zinc-900) inside a zinc-800 surface.
 */
export const surfaceVariants = tv({
  variants: {
    tone: { raised: "bg-zinc-800", inset: "bg-zinc-900" },
  },
  defaultVariants: { tone: "raised" },
});

export type SurfaceTone = NonNullable<
  VariantProps<typeof surfaceVariants>["tone"]
>;

/** The tone of a surface set on one of this tone: one step off it, so it reads as its own sheet. */
export const NESTED_TONE: Record<SurfaceTone, SurfaceTone> = {
  raised: "inset",
  inset: "raised",
};
