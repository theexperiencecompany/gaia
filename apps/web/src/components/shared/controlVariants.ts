import { tv } from "tailwind-variants";

/** light is v2's 15% status tint on a soft Chip or Button (the soft tokens default to v2's 20%); gaia-tint-light in gaia.css. */
export const SOFT_TINT_CLASSES = {
  default: "",
  light: "gaia-tint-light",
} as const;

/** A selected chip lifts on a shadow tinted by its own fill (v2's Chip variant="shadow"); gaia-chip-selected in base.css. */
export const chipVariants = tv({
  variants: {
    isSelected: { true: "gaia-chip-selected", false: "" },
    tint: SOFT_TINT_CLASSES,
  },
  defaultVariants: { isSelected: false, tint: "default" },
});

/** v2's Avatar isBordered: a 2px zinc-700 ring outside a 2px background gap; gaia-avatar-bordered in base.css. */
export const avatarVariants = tv({
  variants: { isBordered: { true: "gaia-avatar-bordered", false: "" } },
  defaultVariants: { isBordered: false },
});

/** v2's wide modal sizes, which v3 lacks (it stops at lg, 32rem); on Modal.Dialog, whose Container then takes no size. */
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

/** v2's small slider (4px track, 20px thumb); md is the gaia-layer default. indigo paints fill and thumbs indigo (quiet hours). */
export const sliderVariants = tv({
  variants: {
    size: { sm: "gaia-slider-sm", md: "" },
    color: { accent: "", indigo: "gaia-slider-indigo" },
  },
  defaultVariants: { size: "md", color: "accent" },
});

/**
 * A text field's size (sm is v2's 32px field on a TextField root or Input), its
 * fill and its placeholder colour. variant goes on the Input, TextArea, InputGroup
 * or Select.Trigger itself: bare drops fill, inset and ring; transparent drops only
 * the fill; underlined is v2's focus underline; translucent and subtle are zinc-800
 * at 50% and 30% (lifting on hover). placeholder takes the tone scale (tone.ts).
 */
export const inputVariants = tv({
  variants: {
    size: { sm: "gaia-input-sm", md: "" },
    variant: {
      default: "",
      bare: "gaia-input-bare",
      transparent: "gaia-input-transparent",
      underlined: "gaia-input-underlined",
      translucent: "gaia-input-translucent",
      subtle: "gaia-input-subtle",
    },
    placeholder: {
      default: "",
      dim: "placeholder:text-zinc-300",
      muted: "placeholder:text-zinc-400",
      faint: "placeholder:text-zinc-500",
      subtle: "placeholder:text-zinc-600",
      ghost: "placeholder:text-zinc-700",
    },
  },
  defaultVariants: { size: "md", variant: "default", placeholder: "default" },
});

/** A Table root's surface: card is v2's default wrapper (16px padded zinc-900 card), plain v2's removeWrapper; gaia.css. */
export const tableVariants = tv({
  variants: {
    surface: { card: "gaia-table-card", plain: "gaia-table-plain" },
  },
  defaultVariants: { surface: "card" },
});

/** surface raised: v2's quieter divider on a raised (zinc-800) surface, zinc-700 at 50%; gaia-separator-raised in gaia.css. */
export const separatorVariants = tv({
  variants: { surface: { default: "", raised: "gaia-separator-raised" } },
  defaultVariants: { surface: "default" },
});

/**
 * An overlay's surface on Popover.Content, Tooltip.Content, Select.Popover or
 * Dropdown.Popover: raised is v2's zinc-800 off a zinc-900 page, secondary the
 * #1a1a1a sidebar surface. backdrop opaque dims the page behind it (v2's backdrop="opaque").
 */
export const overlayVariants = tv({
  variants: {
    surface: {
      default: "",
      raised: "gaia-overlay-raised",
      secondary: "gaia-overlay-secondary",
    },
    backdrop: { none: "", opaque: "gaia-overlay-opaque" },
  },
  defaultVariants: { surface: "default", backdrop: "none" },
});
