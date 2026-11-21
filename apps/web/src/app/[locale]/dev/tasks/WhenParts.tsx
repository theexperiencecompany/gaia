"use client";

import type { ReactNode } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";

/** Every field in the editor: 36px tall, 12px corners, one step darker than the popover. */
export const EDITOR_FIELD = inputVariants({ variant: "sunken" });

/** A quiet text action under a field, on the same 4px inset as the field labels. */
export function TextAction({
  onPress,
  children,
}: {
  onPress: () => void;
  children: ReactNode;
}) {
  return (
    <GaiaButton
      size="sm"
      variant="text"
      inset="snug"
      tone="faint"
      hoverTone="bright"
      onPress={onPress}
      className="h-7 min-w-0 justify-start text-[13px]"
    >
      {children}
    </GaiaButton>
  );
}

/** A setting on one 36px line: its name on the left, its control on the right. */
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex h-9 items-center justify-between gap-3">
      <span className="px-1 text-[13px] text-zinc-500">{label}</span>
      {children}
    </div>
  );
}
