import { tv, type VariantProps } from "tailwind-variants";

/**
 * A card's fill by where it sits: "raised" (zinc-800) on the page background or a
 * zinc-900 panel, "inset" (zinc-900) inside a zinc-800 surface. A faded card
 * (a read notification) drops to 40%.
 */
export const surfaceVariants = tv({
  variants: {
    tone: { raised: "", inset: "" },
    faded: { true: "", false: "" },
  },
  compoundVariants: [
    { tone: "raised", faded: false, class: "bg-zinc-800" },
    { tone: "raised", faded: true, class: "bg-zinc-800/40" },
    { tone: "inset", faded: false, class: "bg-zinc-900" },
    { tone: "inset", faded: true, class: "bg-zinc-900/40" },
  ],
  defaultVariants: { tone: "raised", faded: false },
});

export type SurfaceTone = NonNullable<
  VariantProps<typeof surfaceVariants>["tone"]
>;

/** The tone of a surface set on one of this tone: one step off it, so it reads as its own sheet. */
export const NESTED_TONE: Record<SurfaceTone, SurfaceTone> = {
  raised: "inset",
  inset: "raised",
};
