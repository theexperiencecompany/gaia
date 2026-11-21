"use client";

import { Chip } from "@heroui/react";
import type { ReactNode } from "react";

import { chipVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";

export type ChipTone = "default" | "danger" | "success" | "warning" | "info";

/** A row's facts as small chips, the way the todo list has always shown due dates and checklists. */
export function MetaChip({
  icon,
  tone = "default",
  children,
}: {
  icon?: ReactNode;
  tone?: ChipTone;
  children: ReactNode;
}) {
  return (
    <Chip
      size="sm"
      className={chipVariants({
        status: tone,
        inset: "compact",
        className: shapeVariants({ shape: "sm", className: "h-6" }),
      })}
    >
      {icon}
      <Chip.Label className="text-xs leading-4 font-medium tabular-nums">
        {children}
      </Chip.Label>
    </Chip>
  );
}
