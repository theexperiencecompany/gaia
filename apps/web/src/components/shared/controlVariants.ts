import { tv } from "tailwind-variants";

/** light is v2's 15% status tint on a soft Chip or Button (the soft tokens default to v2's 20%); gaia-tint-light in gaia.css. */
export const SOFT_TINT_CLASSES = {
  default: "",
  light: "gaia-tint-light",
} as const;

/**
 * A selected chip lifts on a shadow tinted by its own fill (v2's Chip variant="shadow");
 * hue secondary repaints an accent chip as v2's purple secondary, a colour v3 dropped,
 * and hue brand gives it v2's text-primary label (#00bbff, not the soft #66aaf9).
 */
export const chipVariants = tv({
  variants: {
    isSelected: { true: "gaia-chip-selected", false: "" },
    tint: SOFT_TINT_CLASSES,
    hue: {
      default: "",
      secondary: "gaia-hue-secondary",
      brand: "gaia-hue-brand",
    },
    // DESIGN.md's status pairs: a 10% tint behind the 400 step of its colour (default is zinc)
    status: {
      none: "",
      default: "bg-zinc-800 text-zinc-300",
      danger: "bg-red-400/10 text-red-400",
      success: "bg-emerald-400/10 text-emerald-400",
      warning: "bg-amber-400/10 text-amber-400",
      info: "bg-blue-400/10 text-blue-400",
    },
    // compact: a row's fact chip, an icon and a few words 6px in with a 4px gap
    inset: { default: "", compact: "gap-1 px-1.5" },
  },
  defaultVariants: {
    isSelected: false,
    tint: "default",
    hue: "default",
    status: "none",
    inset: "default",
  },
});

/**
 * The round to-do checkbox on Checkbox.Control: a 2px ring in its priority's
 * colour (none is zinc-600) that fills solid when ticked, a dark check on it.
 * fill muted is the quieter zinc-500 tick of a subtask; size sm is its 16px box.
 */
export const checkboxVariants = tv({
  base: "rounded-full border-2 bg-transparent shadow-none before:rounded-full",
  variants: {
    ring: {
      none: "border-zinc-600",
      low: "border-blue-500",
      medium: "border-yellow-500",
      high: "border-red-500",
    },
    fill: {
      default:
        "before:bg-zinc-300 in-data-[selected=true]:border-zinc-300 [&_svg]:text-zinc-900",
      muted:
        "before:bg-zinc-500 in-data-[selected=true]:border-zinc-500 [&_svg]:text-zinc-900",
    },
    size: {
      sm: "size-4 [&_svg]:h-2 [&_svg]:w-3",
      md: "size-5 [&_svg]:h-3 [&_svg]:w-4",
    },
  },
  defaultVariants: { ring: "none", fill: "default", size: "md" },
});

/**
 * v2's small switch on v3's Switch parts: a 40x24 round track (zinc-700 off, accent
 * on) with a 16px white thumb 4px in, where v3 draws a squarer track and a dark pill.
 */
export const switchVariants = tv({
  slots: {
    control:
      "h-6 w-10 rounded-full [--switch-control-bg-checked-hover:var(--accent)] [--switch-control-bg-checked:var(--accent)] [--switch-control-bg-hover:var(--color-zinc-700)] [--switch-control-bg-pressed:var(--color-zinc-700)] [--switch-control-bg:var(--color-zinc-700)]",
    thumb:
      "ms-1 size-4 rounded-full bg-white shadow-sm [--switch-thumb-offset:1rem] in-data-[selected=true]:bg-white",
  },
});

/** v2's Avatar isBordered: a 2px zinc-700 ring outside a 2px background gap; gaia-avatar-bordered in base.css. */
export const avatarVariants = tv({
  variants: { isBordered: { true: "gaia-avatar-bordered", false: "" } },
  defaultVariants: { isBordered: false },
});

/** v2's wide modal sizes, which v3 lacks (it stops at lg, 32rem), on Modal.Dialog, whose Container then takes no size; inset none drops v3's 24px dialog padding for a dialog that lays out its own. */
export const modalVariants = tv({
  variants: {
    inset: { none: "p-0" },
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
      // text edited in place: bare, and no minimum height, so the line never moves on focus
      inline: "gaia-input-inline",
      // a control inside a zinc-800 editor: zinc-900, 12px corners, 36px, no ring
      sunken: "gaia-input-sunken",
      // a block of writing on zinc-800: 16px corners, 14px inset, no ring
      filled: "gaia-input-filled",
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

/**
 * surface raised: v2's quieter divider on a raised (zinc-800) surface, zinc-700 at 50%;
 * gaia-separator-raised in gaia.css. surface page: an opaque zinc-800 hairline under a page heading.
 */
export const separatorVariants = tv({
  variants: {
    surface: {
      default: "",
      raised: "gaia-separator-raised",
      page: "rounded-none bg-zinc-800",
    },
  },
  defaultVariants: { surface: "default" },
});

/**
 * An overlay's surface on Popover.Content, Tooltip.Content, Select.Popover or
 * Dropdown.Popover: raised is v2's zinc-800 off a zinc-900 page, secondary the
 * #1a1a1a sidebar surface; accent, foreground and danger are v2's coloured
 * tooltips (color="primary" | "foreground" | "danger"), arrow included.
 * backdrop opaque dims the page behind it (v2's backdrop="opaque").
 */
export const overlayVariants = tv({
  variants: {
    surface: {
      default: "",
      raised: "gaia-overlay-raised",
      secondary: "gaia-overlay-secondary",
      accent: "gaia-overlay-accent",
      foreground: "gaia-overlay-foreground",
      danger: "gaia-overlay-danger",
    },
    backdrop: { none: "", opaque: "gaia-overlay-opaque" },
  },
  defaultVariants: { surface: "default", backdrop: "none" },
});
