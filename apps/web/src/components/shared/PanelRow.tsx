"use client";

import { Button, type ButtonProps } from "@heroui/button";
import type { ComponentType, ReactNode } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { cn } from "@/lib/utils";

interface PanelRowContentProps {
  icon: ComponentType<{ className?: string }>;
  label: string;
  /** One muted line under the label; a row without it lets the label wrap to two lines. */
  summary?: string;
  /** Quiet detail just before the chevron, such as a count or a spinner. */
  end?: ReactNode;
  isMuted?: boolean;
}

/** The Button props every panel row shares, so a row a popover opens looks like the rest. */
export const PANEL_ROW_BUTTON_PROPS = {
  variant: "light",
  radius: "lg",
  className:
    "h-auto min-h-12 w-full min-w-0 justify-start gap-3 px-3 py-2 text-left data-[hover=true]:bg-zinc-700/50",
} as const satisfies ButtonProps;

/** What a panel row shows: icon, label, an optional one-line summary, and a disclosure chevron. */
export function PanelRowContent({
  icon: Icon,
  label,
  summary,
  end,
  isMuted = false,
}: PanelRowContentProps) {
  return (
    <>
      <Icon className="size-4 shrink-0 text-zinc-400" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn(
            "text-xs",
            isMuted ? "text-zinc-500" : "font-medium text-zinc-300",
            summary ? "truncate" : "line-clamp-2 whitespace-normal text-pretty",
          )}
          title={label}
        >
          {label}
        </span>
        {summary && (
          <span className="truncate text-xs text-zinc-500" title={summary}>
            {summary}
          </span>
        )}
      </span>
      {end && (
        <span className="flex shrink-0 items-center text-xs tabular-nums text-zinc-500">
          {end}
        </span>
      )}
      <ChevronRight className="size-4 shrink-0 text-zinc-500" />
    </>
  );
}

/** One quiet side-panel row that opens something when pressed. */
export function PanelRow({
  onPress,
  ...content
}: PanelRowContentProps & { onPress: () => void }) {
  return (
    <Button {...PANEL_ROW_BUTTON_PROPS} onPress={onPress}>
      <PanelRowContent {...content} />
    </Button>
  );
}
