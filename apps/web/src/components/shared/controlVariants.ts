import { tv } from "tailwind-variants";

/** A selected chip lifts on a shadow tinted by its own fill (v2's Chip variant="shadow"); gaia-chip-selected in base.css. */
export const chipVariants = tv({
  variants: { isSelected: { true: "gaia-chip-selected", false: "" } },
  defaultVariants: { isSelected: false },
});

/** v2's Avatar isBordered: a 2px zinc-700 ring outside a 2px background gap; gaia-avatar-bordered in base.css. */
export const avatarVariants = tv({
  variants: { bordered: { true: "gaia-avatar-bordered", false: "" } },
  defaultVariants: { bordered: false },
});

/** v2's Tabs color="primary": the selected tab on the accent with accent-foreground text over the track; gaia-tabs-accent in base.css. */
export const tabsVariants = tv({
  variants: { color: { default: "", accent: "gaia-tabs-accent" } },
  defaultVariants: { color: "default" },
});

/** v2's wide modal sizes, which v3 lacks (it stops at lg, 32rem); on Modal.Dialog inside a size="lg" Container. */
export const modalVariants = tv({
  variants: {
    size: {
      xl: "gaia-modal-xl",
      "2xl": "gaia-modal-2xl",
      "3xl": "gaia-modal-3xl",
      "4xl": "gaia-modal-4xl",
      "5xl": "gaia-modal-5xl",
    },
  },
});

/** v2's small slider (4px track, 20px thumb); md is the gaia-layer default. */
export const sliderVariants = tv({
  variants: { size: { sm: "gaia-slider-sm", md: "" } },
  defaultVariants: { size: "md" },
});

/** v2's small text field (32px, 8px inset) on a TextField root or Input; variant bare/underlined goes on the Input or TextArea itself. */
export const inputVariants = tv({
  variants: {
    size: { sm: "gaia-input-sm", md: "" },
    variant: {
      default: "",
      bare: "gaia-input-bare",
      underlined: "gaia-input-underlined",
    },
  },
  defaultVariants: { size: "md", variant: "default" },
});
