import { tv } from "tailwind-variants";

/**
 * v2's tabs on v3's Tabs parts, slot names as in HeroUI's own tabsVariants.
 * variant styles the list, indicator and panel (solid fills the list; light and
 * underlined do not); size styles each tab; shape pill rounds list, tabs and
 * indicator fully; color accent puts the selected tab on the accent; panel
 * flush drops the panel inset for content that lays itself out.
 */
export const tabsVariants = tv({
  slots: { base: "", tabList: "", tab: "", tabIndicator: "", tabPanel: "" },
  variants: {
    variant: {
      solid: {
        base: "gap-0",
        tabList: "w-fit min-w-0 gap-2 rounded-xl bg-zinc-800 p-1",
        tabIndicator:
          "rounded-lg bg-zinc-700 shadow-[0_0_5px_0_rgb(0_0_0/0.05),0_2px_10px_0_rgb(0_0_0/0.2),inset_0_0_1px_0_rgb(255_255_255/0.15)]",
        tabPanel: "mt-0 px-1 py-3",
      },
      light: {
        base: "gap-0",
        tabList: "w-fit min-w-0 gap-2 rounded-xl p-1",
        tabIndicator:
          "rounded-lg bg-zinc-700 shadow-[0_0_5px_0_rgb(0_0_0/0.05),0_2px_10px_0_rgb(0_0_0/0.2),inset_0_0_1px_0_rgb(255_255_255/0.15)]",
        tabPanel: "mt-0 px-1 py-3",
      },
      underlined: {
        base: "gap-0",
        tabList: "w-fit min-w-0 gap-2 rounded-xl p-1",
        tabIndicator:
          "start-[10%] top-auto bottom-0 h-[2px] w-[80%] rounded-none bg-foreground shadow-[0_1px_0px_0_rgba(0,0,0,0.05)]",
        tabPanel: "mt-0 px-1 py-3",
      },
    },
    size: {
      sm: {
        tab: "h-7 w-full rounded-lg px-3 py-1 text-xs font-normal text-zinc-400",
      },
      md: {
        tab: "h-8 w-full rounded-lg px-3 py-1 text-sm font-normal text-zinc-400",
      },
      lg: {
        tabList: "rounded-2xl",
        tab: "h-9 w-full rounded-xl px-3 py-1 text-base font-normal text-zinc-400",
        tabIndicator: "rounded-xl",
      },
    },
    color: {
      default: { tab: "data-[selected=true]:text-foreground" },
      accent: {
        base: "gaia-tabs-accent",
        tab: "data-[selected=true]:text-accent-foreground",
        tabIndicator: "rounded-lg bg-accent shadow-none",
      },
    },
    shape: {
      default: {},
      pill: {
        tabList: "rounded-full",
        tab: "rounded-full",
        tabIndicator: "rounded-full",
      },
    },
    panel: {
      default: {},
      flush: { tabPanel: "p-0" },
    },
  },
  defaultVariants: {
    size: "md",
    shape: "default",
    color: "default",
    panel: "default",
  },
});
