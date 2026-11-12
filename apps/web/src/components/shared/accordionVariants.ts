import { tv } from "tailwind-variants";

/**
 * v2's accordion on v3's Accordion parts, slot names as in HeroUI's own
 * accordionVariants: no trigger inset or hover fill, a right chevron turning
 * down when open, and a padded panel. density compact is v2's isCompact;
 * flush drops the trigger's vertical padding for a row that sets its own.
 */
export const accordionVariants = tv({
  slots: {
    base: "",
    trigger: "gap-3 px-0 hover:bg-transparent",
    indicator: "rotate-90 text-zinc-500 data-[expanded=true]:rotate-0",
    panel: "",
  },
  variants: {
    variant: {
      light: { base: "px-2" },
      shadow: {
        base: "rounded-xl bg-zinc-900 px-4 shadow-[0_0_15px_0_rgb(0_0_0/0.06),0_2px_30px_0_rgb(0_0_0/0.22),inset_0_0_1px_0_rgb(255_255_255/0.15)]",
      },
    },
    density: {
      default: { trigger: "py-4", panel: "py-2" },
      compact: { trigger: "py-2", panel: "py-1" },
      flush: { trigger: "py-0", panel: "py-1" },
    },
  },
  defaultVariants: { density: "default" },
});
