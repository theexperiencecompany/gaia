/**
 * HeroUI v2 tabs slot styling on the v3 Tabs compounds (theme 2.4.26).
 * v2 tab lists hug their content with 8px-radius tabs and a sliding cursor; v3 stretches
 * the list full width with pill tabs, and draws no cursor unless Tabs.Indicator is rendered.
 * Compose one list, one tab size, one selected colour and one indicator per v2 variant/color.
 */
export const TABS_ROOT = "gap-0";

/** v2 `solid` list; `light` and `underlined` drop the fill. */
export const TABS_LIST =
  "w-fit min-w-0 gap-2 rounded-medium bg-default-100 p-1";
export const TABS_LIST_LIGHT = "w-fit min-w-0 gap-2 rounded-medium p-1";

export const TABS_TAB =
  "h-8 w-full rounded-small px-3 py-1 text-small font-normal text-default-500";
export const TABS_TAB_SM =
  "h-7 w-full rounded-small px-3 py-1 text-tiny font-normal text-default-500";

export const TABS_SELECTED = "data-[selected=true]:text-foreground";
export const TABS_SELECTED_PRIMARY =
  "data-[selected=true]:text-primary-foreground";

/** v2 cursor for color="default" (dark: default #3f3f46 with shadow-small). */
export const TABS_INDICATOR =
  "rounded-small bg-default-200 shadow-[0_0_5px_0_rgb(0_0_0/0.05),0_2px_10px_0_rgb(0_0_0/0.2),inset_0_0_1px_0_rgb(255_255_255/0.15)]";
export const TABS_INDICATOR_PRIMARY = "rounded-small bg-primary shadow-none";
export const TABS_INDICATOR_UNDERLINED =
  "start-[10%] top-auto bottom-0 h-[2px] w-[80%] rounded-none bg-foreground shadow-[0_1px_0px_0_rgba(0,0,0,0.05)]";

export const TABS_PANEL = "mt-0 px-1 py-3";
