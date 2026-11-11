import type { ButtonProps } from "@heroui/button";

/** The Button props every panel row shares, so a row a popover opens looks like the rest. */
export const PANEL_ROW_BUTTON_PROPS = {
  variant: "light",
  radius: "lg",
  className:
    "h-auto min-h-12 w-full min-w-0 justify-start gap-3 px-3 py-2 text-left data-[hover=true]:bg-zinc-700/50",
} as const satisfies ButtonProps;
