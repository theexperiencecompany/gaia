"use client";

import { Chip } from "@heroui/react";
import {
  Calendar03Icon,
  CalendarAdd01Icon,
  FlashIcon,
  RepeatIcon,
} from "@icons";
import type { ComponentType, ReactNode } from "react";

import { chipVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";
import { AppIcon } from "./AppIcons";
import type { TaskWhen, WhenKind } from "./taskModel";

type IconComponent = ComponentType<{ className?: string; size?: number }>;

export const WHEN_ICONS: Record<WhenKind, IconComponent> = {
  anytime: CalendarAdd01Icon,
  at: Calendar03Icon,
  schedule: RepeatIcon,
  event: FlashIcon,
};

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

/**
 * When a task is due or runs, always as one chip. Colour is kept for the two that
 * need you today; an event trigger leads with the app that fires it.
 */
export function WhenChip({ when }: { when: TaskWhen }) {
  if (!when.label) return null;
  const Icon = WHEN_ICONS[when.kind];
  const tone: ChipTone = when.overdue
    ? "danger"
    : when.isToday
      ? "success"
      : when.kind === "schedule"
        ? "info"
        : "default";

  return (
    <MetaChip
      tone={tone}
      icon={
        when.app ? (
          <AppIcon id={when.app} size={14} />
        ) : (
          <Icon className="size-3.5" />
        )
      }
    >
      {when.overdue ? `Overdue, ${when.label}` : when.label}
    </MetaChip>
  );
}
