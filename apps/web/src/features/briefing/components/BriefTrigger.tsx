"use client";

import type { ComponentProps } from "react";
import { mergeProps } from "react-aria";

import { cn } from "@/lib/utils";

import type { BriefTriggerState } from "../hooks/useOpenBrief";

type BriefTriggerProps = Omit<ComponentProps<"button">, "onClick"> & {
  trigger: Pick<BriefTriggerState, "warm" | "isBusy">;
  /** Called on press; a letter passes where it lies so it can open from there. */
  onPress: () => void;
};

/**
 * The press target of every folded brief: it readies the edition as the
 * pointer or focus arrives and opens the letter on press. Any extra props
 * (a tooltip's trigger props, an accessible name) pass through to the button.
 */
export function BriefTrigger({
  trigger,
  onPress,
  className,
  ...props
}: BriefTriggerProps) {
  return (
    <button
      type="button"
      // Chained, so a wrapping tooltip's own focus and pointer handlers still run.
      {...mergeProps(props, {
        onClick: onPress,
        onPointerEnter: trigger.warm,
        onPointerDown: trigger.warm,
        onFocus: trigger.warm,
      })}
      aria-busy={trigger.isBusy}
      className={cn(
        "cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-accent",
        className,
      )}
    />
  );
}
